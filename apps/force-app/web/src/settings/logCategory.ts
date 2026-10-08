// Settings > Logs colours each line by what it is about, so an operator scanning a long log can
// pick out recording activity from HTTP polling noise and from errors raised in the web UI
// (the UI forwards its own errors to the backend log under force_app.client).

export type LogCategory = 'error' | 'warning' | 'network' | 'ui' | 'recording' | 'other';

export const LOG_CATEGORIES: { key: LogCategory; label: string }[] = [
	{ key: 'error', label: 'Errors' },
	{ key: 'warning', label: 'Warnings' },
	{ key: 'network', label: 'Network' },
	{ key: 'ui', label: 'UI' },
	{ key: 'recording', label: 'Recording' },
	{ key: 'other', label: 'Other' },
];

export interface LogLike { level: string; logger: string; message: string; }

/** Severity wins over the line's type: a failed HTTP request is an error first. */
export function logCategory(r: LogLike): LogCategory {
	const level = (r.level || '').toUpperCase();
	if (level === 'ERROR' || level === 'CRITICAL') return 'error';
	if (level === 'WARNING' || level === 'WARN') return 'warning';
	const logger = r.logger || '';
	const message = r.message || '';
	if (/^(httpx|httpcore|urllib3)(\.|$)/.test(logger) || message.includes('HTTP Request')) return 'network';
	if (/^force_app\.client(\.|$)/.test(logger)) return 'ui';
	if (/^force_app\.session(\.|$)/.test(logger) || /finalize/i.test(message)) return 'recording';
	return 'other';
}
