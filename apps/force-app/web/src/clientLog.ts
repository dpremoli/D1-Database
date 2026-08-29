// Sends renderer crashes to the same backend log Settings > Logs already shows, so a frontend
// error doesn't just vanish into DevTools the moment the window closes — it's also the source
// material a bug report can attach. Best-effort only: never throws, never awaited by its caller.
import { getConfig } from './config';

// Keyed per message (not a single global cooldown) so an unrelated second error arriving soon
// after the first still gets through — a global throttle would silently drop it, hiding exactly
// the kind of second failure this feature exists to catch.
const lastSendByKey = new Map<string, number>();
const MIN_INTERVAL_MS = 2000; // client-side throttle; the backend also dedups identical messages

export function reportClientError(message: string, source = 'renderer', route = ''): void {
	const msg = String(message).slice(0, 4000);
	const key = `${source}:${route}:${msg.slice(0, 200)}`;
	const now = Date.now();
	const last = lastSendByKey.get(key);
	if (last !== undefined && now - last < MIN_INTERVAL_MS) return;
	// Unbounded growth isn't realistic in a single renderer session, but bound it anyway rather
	// than trust that assumption forever.
	if (lastSendByKey.size > 200) lastSendByKey.clear();
	lastSendByKey.set(key, now);
	try {
		const body = JSON.stringify({ message: msg, level: 'ERROR', source, route });
		fetch(`${getConfig().recorderUrl}/logs/client`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body,
			keepalive: true,
		}).catch(() => {}); // backend unreachable — nothing else to do
	} catch {
		// stringify or fetch construction failed — swallow, this path must never itself throw
	}
}

// ---- console ring buffer (bug-report attachment) ----
// reportClientError() only forwards errors, and it throttles + dedups them. A bug report wants the
// run-up as well: the warnings and logs immediately before the failure, in order, including the
// repeats a throttle drops. Kept in memory only — nothing is sent anywhere until the operator
// actually files a report.
const CONSOLE_BUFFER_MAX = 300;
const consoleBuffer: string[] = [];

function pushConsole(level: string, args: unknown[]): void {
	try {
		const text = args
			.map((a) => {
				if (typeof a === 'string') return a;
				if (a instanceof Error) return a.stack || `${a.name}: ${a.message}`;
				try {
					return JSON.stringify(a);
				} catch {
					return String(a); // circular or otherwise unserialisable
				}
			})
			.join(' ')
			.slice(0, 2000);
		consoleBuffer.push(`${new Date().toISOString()} ${level} ${text}`);
		if (consoleBuffer.length > CONSOLE_BUFFER_MAX) consoleBuffer.shift();
	} catch {
		// capturing a log line must never break the app that produced it
	}
}

/** Oldest-first console history for the bug-report form. */
export function getConsoleTail(): string {
	return consoleBuffer.join('\n');
}

let installed = false;

export function installGlobalErrorReporting(currentRoute: () => string): void {
	if (installed) return; // guard against duplicate listeners if bootstrap() ever re-runs (HMR)
	installed = true;
	// Wrap rather than replace: the original still runs, so DevTools behaves exactly as before.
	for (const level of ['log', 'info', 'warn', 'error'] as const) {
		const original = console[level].bind(console);
		console[level] = (...args: unknown[]) => {
			pushConsole(level.toUpperCase(), args);
			original(...args);
		};
	}
	window.addEventListener('error', (e) => {
		const msg = e.error?.stack || e.message || 'unknown window error';
		pushConsole('ERROR', [msg]);
		reportClientError(msg, 'renderer', currentRoute());
	});
	window.addEventListener('unhandledrejection', (e) => {
		const reason: any = e.reason;
		const msg = reason?.stack || reason?.message || String(reason ?? 'unhandled rejection');
		pushConsole('UNHANDLED', [msg]);
		reportClientError(msg, 'renderer', currentRoute());
	});
}
