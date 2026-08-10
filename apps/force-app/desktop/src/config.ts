import fs from 'node:fs';
import path from 'node:path';

export interface DesktopConfig {
  directusUrl: string;
  filterUrl: string;
  octreeUrl: string;
  recorderUrl: string;
}

const DEFAULT_DIRECTUS_URL = 'https://d1-server.tail54eeb6.ts.net';

export function defaultConfig(): DesktopConfig {
  return {
    directusUrl: DEFAULT_DIRECTUS_URL,
    filterUrl: `${DEFAULT_DIRECTUS_URL}/filter`,
    octreeUrl: `${DEFAULT_DIRECTUS_URL}/octrees`,
    recorderUrl: 'http://127.0.0.1:8200',
  };
}

/** Reads/writes `<userData>/config.json` — the same runtime-config file
 * `apps/force-app/web/src/config.ts` fetches from `${BASE_URL}config.json`. The desktop protocol
 * handler (Task 4) intercepts that request and serves this file instead of a bundled one, because
 * only this file can carry the port the sidecar actually bound to. */
export class ConfigStore {
  private readonly filePath: string;

  constructor(userDataDir: string) {
    this.filePath = path.join(userDataDir, 'config.json');
  }

  seedIfMissing(): DesktopConfig {
    if (fs.existsSync(this.filePath)) return this.read();
    const cfg = defaultConfig();
    this.write(cfg);
    return cfg;
  }

  read(): DesktopConfig {
    const raw = fs.readFileSync(this.filePath, 'utf-8');
    return { ...defaultConfig(), ...JSON.parse(raw) };
  }

  write(cfg: DesktopConfig): void {
    fs.mkdirSync(path.dirname(this.filePath), { recursive: true });
    fs.writeFileSync(this.filePath, JSON.stringify(cfg, null, 2));
  }

  /** Called once the sidecar's resolved port is known. */
  setRecorderPort(port: number): DesktopConfig {
    const cfg = this.seedIfMissing();
    cfg.recorderUrl = `http://127.0.0.1:${port}`;
    this.write(cfg);
    return cfg;
  }

  get path(): string {
    return this.filePath;
  }
}
