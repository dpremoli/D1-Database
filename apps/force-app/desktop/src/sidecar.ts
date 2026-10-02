import { spawn, execFile, type ChildProcess } from 'node:child_process';

export type SidecarState = 'starting' | 'ready' | 'restarting' | 'crashed' | 'stopped';

export interface SidecarOptions {
  exePath: string;
  args: string[];
  cwd?: string;
  /** Extra environment for the child, merged over (not replacing) the parent's env. */
  env?: NodeJS.ProcessEnv;
  port: number;
  healthUrl: string;
  readyTimeoutMs?: number;
  maxRestarts?: number;
  /** How often a ready backend is re-checked on `healthUrl`. 0 turns the liveness probe off. */
  livenessIntervalMs?: number;
  /** How long one liveness check may take before it counts as failed. */
  livenessTimeoutMs?: number;
  /** Failed checks in a row before the backend is treated as hung and restarted. */
  livenessFailures?: number;
  onStateChange?: (state: SidecarState, detail?: string) => void;
}

const DEFAULT_READY_TIMEOUT_MS = 20_000;
const DEFAULT_MAX_RESTARTS = 5;
const BACKOFF_BASE_MS = 1000;
// #106: generous on purpose. /health is a trivial async handler, so a backend that cannot answer
// it four times running (~70 s) has a blocked event loop: the live websocket is stalled and every
// other endpoint hangs with it, a recording included. A slow finalize runs in a worker thread and
// does not hold the loop for anything like that long, so it should not trip this.
const DEFAULT_LIVENESS_INTERVAL_MS = 10_000;
const DEFAULT_LIVENESS_TIMEOUT_MS = 8_000;
const DEFAULT_LIVENESS_FAILURES = 4;
// How long a POSIX child gets to exit on SIGTERM before it is SIGKILLed.
const TERM_GRACE_MS = 3_000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function isHealthy(url: string, timeoutMs: number): Promise<boolean> {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
    return res.ok;
  } catch {
    return false;
  }
}

async function waitForHealthy(url: string, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(1500) });
      if (res.ok) return true;
    } catch {
      /* not up yet */
    }
    await sleep(300);
  }
  return false;
}

/** Windows: kill the whole process tree. A plain `proc.kill()` leaves an orphaned uvicorn
 * holding the port, which blocks the next launch — see the sidecar spec's "Quit" note. */
function killTree(pid: number): Promise<void> {
  return new Promise((resolve) => {
    execFile('taskkill', ['/pid', String(pid), '/T', '/F'], () => resolve());
  });
}

/** Ends the child and resolves once it has exited. taskkill on Windows; elsewhere (dev on
 * Linux/macOS, and the unit tests) there is no taskkill, so SIGTERM, then SIGKILL if the process
 * is too wedged to act on it — a backend stuck in a blocking write may never get to its handler. */
function terminate(proc: ChildProcess): Promise<void> {
  if (proc.pid == null || proc.exitCode !== null || proc.signalCode !== null) return Promise.resolve();
  const exited = new Promise<void>((resolve) => proc.once('exit', () => resolve()));
  if (process.platform === 'win32') {
    void killTree(proc.pid);
  } else {
    proc.kill('SIGTERM');
    const escalate = setTimeout(() => proc.kill('SIGKILL'), TERM_GRACE_MS);
    void exited.then(() => clearTimeout(escalate));
  }
  // Never wait forever: a quit must not hang on a child that refuses to report its exit.
  return Promise.race([exited, sleep(TERM_GRACE_MS + 2_000)]);
}

/** Spawns the recorder backend, polls it healthy, and restarts it with capped exponential
 * backoff if it exits unexpectedly. One instance per app run. */
export class SidecarSupervisor {
  private readonly opts: Required<Omit<SidecarOptions, 'onStateChange' | 'cwd' | 'env'>> &
    Pick<SidecarOptions, 'onStateChange' | 'cwd' | 'env'>;
  private proc: ChildProcess | null = null;
  private state: SidecarState = 'stopped';
  private detail: string | undefined;
  private restarts = 0;
  private stopping = false;
  private livenessTimer: ReturnType<typeof setTimeout> | null = null;
  // Why the current process was killed by the liveness probe, if it was — reported in place of
  // the bare exit code, which for a killed process says nothing useful.
  private hungReason: string | null = null;

  constructor(opts: SidecarOptions) {
    this.opts = {
      readyTimeoutMs: DEFAULT_READY_TIMEOUT_MS,
      maxRestarts: DEFAULT_MAX_RESTARTS,
      livenessIntervalMs: DEFAULT_LIVENESS_INTERVAL_MS,
      livenessTimeoutMs: DEFAULT_LIVENESS_TIMEOUT_MS,
      livenessFailures: DEFAULT_LIVENESS_FAILURES,
      ...opts,
    };
  }

  getState(): SidecarState {
    return this.state;
  }

  getPid(): number | null {
    return this.proc?.pid ?? null;
  }

  getRestartCount(): number {
    return this.restarts;
  }

  lastDetail(): string | undefined {
    return this.detail;
  }

  private setState(s: SidecarState, detail?: string): void {
    this.state = s;
    this.detail = detail;
    this.opts.onStateChange?.(s, detail);
  }

  async start(): Promise<void> {
    this.stopping = false;
    this.restarts = 0;
    await this.spawnAndWait();
  }

  private spawnProcess(): ChildProcess {
    const proc = spawn(this.opts.exePath, this.opts.args, {
      cwd: this.opts.cwd,
      // Merge over the parent env rather than replacing it — the child still needs PATH,
      // SystemRoot, etc. Undefined opts.env spreads to nothing, so this is a no-op by default.
      env: { ...process.env, ...this.opts.env },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
    // #106: BOTH pipes must be read. stdout used to be piped and never read; once its OS buffer
    // filled (64 KB, i.e. a few hundred uvicorn access-log lines — replay's ~3 spectrum
    // requests/s got there in minutes), the backend's next write to it blocked, and with it the
    // event loop: every endpoint and the live websocket hung, with no exit for this supervisor to
    // notice. Both streams feed the same short tail, kept for the crash dialog.
    let outputTail = '';
    const keepTail = (chunk: Buffer) => {
      outputTail = (outputTail + chunk.toString()).slice(-4000);
    };
    proc.stdout?.on('data', keepTail);
    proc.stderr?.on('data', keepTail);
    proc.on('exit', (code, signal) => {
      this.stopLiveness();
      if (this.stopping) {
        this.setState('stopped');
        return;
      }
      const why = this.hungReason ?? `exit code=${code} signal=${signal}`;
      void this.handleUnexpectedExit(`${why}\n${outputTail}`).catch(
        (err) => {
          console.error('sidecar: handleUnexpectedExit failed', err);
        },
      );
    });
    proc.on('error', (err) => {
      if (this.stopping) {
        this.setState('stopped');
        return;
      }
      void this.handleUnexpectedExit(`spawn error: ${err.message}`).catch((handlerErr) => {
        console.error('sidecar: handleUnexpectedExit failed', handlerErr);
      });
    });
    return proc;
  }

  private async handleUnexpectedExit(detail: string): Promise<void> {
    if (this.restarts >= this.opts.maxRestarts) {
      this.setState('crashed', `giving up after ${this.restarts} restart(s)\n${detail}`);
      return;
    }
    this.restarts += 1;
    const delay = BACKOFF_BASE_MS * 2 ** (this.restarts - 1);
    // The cause's first line rides along, so main.ts can log WHY once the backend is back up.
    const cause = detail.split('\n')[0];
    this.setState('restarting', `attempt ${this.restarts}/${this.opts.maxRestarts} in ${delay}ms: ${cause}`);
    await sleep(delay);
    if (this.stopping) return;
    await this.spawnAndWait();
  }

  private async spawnAndWait(): Promise<void> {
    this.setState('starting');
    this.hungReason = null;
    this.proc = this.spawnProcess();
    const ready = await waitForHealthy(this.opts.healthUrl, this.opts.readyTimeoutMs);
    if (ready) {
      this.setState('ready');
      this.startLiveness(this.proc);
    } else if (!this.stopping) {
      this.setState('crashed', `did not become healthy within ${this.opts.readyTimeoutMs}ms`);
    }
  }

  /** #106: health used to be checked only at startup, so a backend that hung (rather than
   * exited) left the app silently dead until the operator restarted it. This keeps checking a
   * ready backend and, after `livenessFailures` misses in a row, kills it; the exit then takes
   * the normal restart path, and the restart sends the renderer to Record, where the recovery
   * banner offers whatever the hung session had captured. */
  private startLiveness(proc: ChildProcess): void {
    if (this.opts.livenessIntervalMs <= 0) return;
    let failures = 0;
    const tick = async () => {
      this.livenessTimer = null;
      if (this.stopping || this.proc !== proc) return;
      const ok = await isHealthy(this.opts.healthUrl, this.opts.livenessTimeoutMs);
      if (this.stopping || this.proc !== proc || proc.exitCode !== null) return;
      failures = ok ? 0 : failures + 1;
      if (failures >= this.opts.livenessFailures) {
        this.hungReason = `stopped answering ${this.opts.healthUrl} (${failures} checks in a row); restarted it`;
        console.error(`sidecar: ${this.hungReason}`);
        await terminate(proc);
        return;
      }
      this.scheduleLiveness(tick);
    };
    this.scheduleLiveness(tick);
  }

  private scheduleLiveness(tick: () => Promise<void>): void {
    // One check at a time — a setTimeout chain, not setInterval, so a slow check never overlaps
    // the next. unref'd so a pending check never keeps the process alive on its own.
    this.livenessTimer = setTimeout(() => void tick(), this.opts.livenessIntervalMs);
    this.livenessTimer.unref?.();
  }

  private stopLiveness(): void {
    if (this.livenessTimer) clearTimeout(this.livenessTimer);
    this.livenessTimer = null;
  }

  async stop(): Promise<void> {
    this.stopping = true;
    this.stopLiveness();
    if (!this.proc || this.proc.pid == null || this.proc.exitCode !== null) {
      this.setState('stopped');
      return;
    }
    await terminate(this.proc);
    this.setState('stopped');
  }
}
