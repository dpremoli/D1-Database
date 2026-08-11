import { spawn, execFile, type ChildProcess } from 'node:child_process';

export type SidecarState = 'starting' | 'ready' | 'restarting' | 'crashed' | 'stopped';

export interface SidecarOptions {
  exePath: string;
  args: string[];
  cwd?: string;
  port: number;
  healthUrl: string;
  readyTimeoutMs?: number;
  maxRestarts?: number;
  onStateChange?: (state: SidecarState, detail?: string) => void;
}

const DEFAULT_READY_TIMEOUT_MS = 20_000;
const DEFAULT_MAX_RESTARTS = 5;
const BACKOFF_BASE_MS = 1000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
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

/** Spawns the recorder backend, polls it healthy, and restarts it with capped exponential
 * backoff if it exits unexpectedly. One instance per app run. */
export class SidecarSupervisor {
  private readonly opts: Required<Omit<SidecarOptions, 'onStateChange' | 'cwd'>> &
    Pick<SidecarOptions, 'onStateChange' | 'cwd'>;
  private proc: ChildProcess | null = null;
  private state: SidecarState = 'stopped';
  private detail: string | undefined;
  private restarts = 0;
  private stopping = false;

  constructor(opts: SidecarOptions) {
    this.opts = {
      readyTimeoutMs: DEFAULT_READY_TIMEOUT_MS,
      maxRestarts: DEFAULT_MAX_RESTARTS,
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
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
    let stderrTail = '';
    proc.stderr?.on('data', (chunk: Buffer) => {
      stderrTail = (stderrTail + chunk.toString()).slice(-4000);
    });
    proc.on('exit', (code, signal) => {
      if (this.stopping) {
        this.setState('stopped');
        return;
      }
      void this.handleUnexpectedExit(`exit code=${code} signal=${signal}\n${stderrTail}`).catch(
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
    this.setState('restarting', `attempt ${this.restarts}/${this.opts.maxRestarts} in ${delay}ms`);
    await sleep(delay);
    if (this.stopping) return;
    await this.spawnAndWait();
  }

  private async spawnAndWait(): Promise<void> {
    this.setState('starting');
    this.proc = this.spawnProcess();
    const ready = await waitForHealthy(this.opts.healthUrl, this.opts.readyTimeoutMs);
    if (ready) {
      this.setState('ready');
    } else if (!this.stopping) {
      this.setState('crashed', `did not become healthy within ${this.opts.readyTimeoutMs}ms`);
    }
  }

  async stop(): Promise<void> {
    this.stopping = true;
    const pid = this.proc?.pid;
    if (pid == null || this.proc?.exitCode !== null) {
      this.setState('stopped');
      return;
    }
    await killTree(pid);
    this.setState('stopped');
  }
}
