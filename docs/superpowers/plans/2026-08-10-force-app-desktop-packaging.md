# Force App Desktop Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package `apps/force-app` as a single-window Electron desktop app — recorder backend
bundled as a PyInstaller sidecar, SPA served from a custom `app://force` origin, unsigned
installer updated over a Tailscale-only feed — implementing ADR-0010 steps 3–4.

**Architecture:** A new `apps/force-app/desktop` npm workspace holds the Electron main process.
On launch it seeds a `config.json` in `userData`, resolves a free port, spawns the recorder
backend (dev: the existing Python venv via `uvicorn`; packaged: a frozen `force-app-backend.exe`),
polls it healthy, then loads the unmodified `apps/force-app/web` SPA build over a registered
`app://force` scheme (never `file://`, which breaks CORS against Directus). A supervisor restarts
a crashed backend with capped exponential backoff and kills the whole process tree on quit.
`electron-builder` produces an NSIS installer; `electron-updater` checks a generic feed served by
the Caddy instance already running on `d1-server`, reachable only over Tailscale.

**Tech Stack:** Electron + TypeScript (main process, CommonJS), `electron-builder` +
`electron-updater`, PyInstaller (backend freeze), Vitest (unit), Playwright `_electron` (smoke),
GitHub Actions (Windows runner).

## Global Constraints

- Electron, not Tauri — see `docs/superpowers/specs/2026-08-10-force-app-desktop-packaging-design.md`.
- Package inside the monorepo at `apps/force-app/desktop/`; do not extract the repo first.
- v1 requires Directus. No local-only / no-Directus mode, no macOS/Linux builds, no code signing —
  all explicitly out of scope for v1.
- The SPA must never load from `file://`. It is served from a registered `app://force` custom
  scheme (`standard` + `secure` + `corsEnabled`) so it has a real, stable origin.
- PyInstaller must build **one-folder**, not one-file — a one-file build re-extracts ~200 MB of
  scipy to a temp dir on every launch.
- Default recorder port is `8200`; probe first and fall back to a free port rather than failing
  when it's held.
- The installer ships **unsigned** and the update feed is **Tailscale-only** (static files behind
  the Caddy proxy on `d1-server`, never public GitHub Releases). These two facts are coupled:
  `electron-updater` skips signature verification when unsigned, so the transport being private is
  the only thing protecting the update channel.
- CI cannot publish directly to the feed (`d1-server` is tailnet-only, GitHub runners are not).
  Publishing is a **pull**, via a script run on `d1-server` using the `gh` CLI — never a push from
  CI, and no tailnet credential in GitHub secrets.
- Windows-only throughout (matches the existing backend, which is already Windows-only).

---

## Task 1: Scaffold the Electron workspace

**Files:**
- Create: `apps/force-app/desktop/package.json`
- Create: `apps/force-app/desktop/tsconfig.json`
- Create: `apps/force-app/desktop/src/main.ts`
- Create: `apps/force-app/desktop/static/loading.html`
- Modify: `package.json` (repo root) — add the new workspace

**Interfaces:**
- Produces: an `electron .` -launchable app whose entry is `dist/main.js` (compiled from
  `src/main.ts` by `tsc`). Later tasks add modules under `src/` and extend `main.ts` in place.

- [ ] **Step 1: Add the workspace to the root package.json**

Modify `package.json` (repo root), the `workspaces` array:

```json
  "workspaces": [
    "packages/*",
    "apps/force-app/web",
    "apps/force-app/desktop",
    "core/extensions/d1-force-dashboard"
  ],
```

- [ ] **Step 2: Create the package manifest**

Create `apps/force-app/desktop/package.json`:

```json
{
  "name": "force-app-desktop",
  "private": true,
  "version": "0.1.0",
  "description": "Electron shell packaging the force-app SPA and recorder backend as a single Windows installer.",
  "main": "dist/main.js",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "dev": "npm run build && electron .",
    "typecheck": "tsc -p tsconfig.json --noEmit",
    "test": "vitest run"
  },
  "dependencies": {},
  "devDependencies": {
    "@types/node": "^22.10.0",
    "electron": "^33.0.0",
    "typescript": "^5.7.3",
    "vitest": "^4.1.10"
  }
}
```

- [ ] **Step 3: Install dependencies and pin to the latest Electron**

Run from the repo root:

```bash
npm install
npm install --save-dev electron@latest -w force-app-desktop
```

The second command re-pins `electron` in `apps/force-app/desktop/package.json` to whatever is
actually current, since the version above is a floor, not a target.

- [ ] **Step 4: Create the TypeScript config**

Create `apps/force-app/desktop/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "CommonJS",
    "moduleResolution": "Node",
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "types": ["node"]
  },
  "include": ["src/**/*.ts"]
}
```

- [ ] **Step 5: Create the loading screen**

Create `apps/force-app/desktop/static/loading.html`:

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Force App</title>
  <style>
    body { margin: 0; height: 100vh; display: flex; align-items: center; justify-content: center;
           background: #0b1220; color: #cbd5e1; font: 14px system-ui, sans-serif; }
    .spinner { width: 28px; height: 28px; border: 3px solid #334155; border-top-color: #38bdf8;
               border-radius: 50%; animation: spin 0.8s linear infinite; margin-right: 12px; }
    @keyframes spin { to { transform: rotate(360deg); } }
    .row { display: flex; align-items: center; }
  </style>
</head>
<body>
  <div class="row"><div class="spinner"></div>Starting the recorder backend&hellip;</div>
</body>
</html>
```

`static/` sits next to `src/`, not inside it, because `tsc` only emits `.ts` files — the loading
screen has to be shipped as-is. Task 11's `electron-builder` file list includes `static/**/*`
alongside `dist/**/*` for the same reason.

- [ ] **Step 6: Create the minimal main process**

Create `apps/force-app/desktop/src/main.ts`:

```ts
import { app, BrowserWindow } from 'electron';
import path from 'node:path';

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1500,
    height: 950,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  void win.loadFile(path.join(__dirname, '..', 'static', 'loading.html'));
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
```

- [ ] **Step 7: Build and run**

```bash
npm run build -w force-app-desktop
npm run dev -w force-app-desktop
```

Expected: an Electron window opens showing "Starting the recorder backend…" with a spinner.
Close the window to quit.

- [ ] **Step 8: Commit**

```bash
git add package.json package-lock.json apps/force-app/desktop
git commit -m "feat(force-app-desktop): scaffold the Electron workspace"
```

---

## Task 2: Config store

**Files:**
- Create: `apps/force-app/desktop/src/config.ts`
- Test: `apps/force-app/desktop/src/config.test.ts`

**Interfaces:**
- Produces: `ConfigStore` (constructor `(userDataDir: string)`), methods `seedIfMissing()`,
  `read()`, `write(cfg)`, `setRecorderPort(port)`, getter `path`. Type `DesktopConfig` with fields
  `directusUrl`, `filterUrl`, `octreeUrl`, `recorderUrl` — the same four keys
  `apps/force-app/web/src/config.ts` reads from `config.json`. `defaultConfig()` seeds
  `directusUrl` to `https://d1-server.tail54eeb6.ts.net` (the same tailnet default the backend
  already uses in `app/main.py`'s doctor endpoint) and `recorderUrl` to `http://127.0.0.1:8200`.

- [ ] **Step 1: Write the failing tests**

Create `apps/force-app/desktop/src/config.test.ts`:

```ts
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ConfigStore, defaultConfig } from './config';

describe('ConfigStore', () => {
  let dir: string;

  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), 'force-app-config-'));
  });

  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it('seeds config.json with defaults on first run', () => {
    const store = new ConfigStore(dir);
    const cfg = store.seedIfMissing();
    expect(cfg).toEqual(defaultConfig());
    expect(fs.existsSync(path.join(dir, 'config.json'))).toBe(true);
  });

  it('leaves an existing config.json untouched on a second seed call', () => {
    const store = new ConfigStore(dir);
    store.seedIfMissing();
    store.write({ ...defaultConfig(), directusUrl: 'https://custom.example' });
    const cfg = store.seedIfMissing();
    expect(cfg.directusUrl).toBe('https://custom.example');
  });

  it('setRecorderPort patches only recorderUrl, preserving other fields', () => {
    const store = new ConfigStore(dir);
    store.seedIfMissing();
    store.write({ ...defaultConfig(), directusUrl: 'https://custom.example' });
    const cfg = store.setRecorderPort(8231);
    expect(cfg.recorderUrl).toBe('http://127.0.0.1:8231');
    expect(cfg.directusUrl).toBe('https://custom.example');
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm run test -w force-app-desktop`
Expected: FAIL — `./config` has no exported member `ConfigStore`.

- [ ] **Step 3: Implement**

Create `apps/force-app/desktop/src/config.ts`:

```ts
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `npm run test -w force-app-desktop`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/force-app/desktop/src/config.ts apps/force-app/desktop/src/config.test.ts
git commit -m "feat(force-app-desktop): userData config store"
```

---

## Task 3: Port resolver

**Files:**
- Create: `apps/force-app/desktop/src/port.ts`
- Test: `apps/force-app/desktop/src/port.test.ts`

**Interfaces:**
- Produces: `isPortFree(port, host?): Promise<boolean>`,
  `findAvailablePort(preferred, range?): Promise<number>` — throws if no free port is found in
  `[preferred, preferred + range]`.

- [ ] **Step 1: Write the failing tests**

Create `apps/force-app/desktop/src/port.test.ts`:

```ts
import { describe, it, expect, afterEach } from 'vitest';
import net from 'node:net';
import { isPortFree, findAvailablePort } from './port';

describe('port resolver', () => {
  let holder: net.Server | undefined;

  afterEach(async () => {
    await new Promise<void>((resolve) => (holder ? holder.close(() => resolve()) : resolve()));
    holder = undefined;
  });

  it('reports a genuinely free port as free', async () => {
    expect(await isPortFree(48213)).toBe(true);
  });

  it('reports a held port as not free', async () => {
    holder = net.createServer();
    await new Promise<void>((resolve) => holder!.listen(48214, '127.0.0.1', () => resolve()));
    expect(await isPortFree(48214)).toBe(false);
  });

  it('falls back to the next free port when the preferred one is held', async () => {
    holder = net.createServer();
    await new Promise<void>((resolve) => holder!.listen(48215, '127.0.0.1', () => resolve()));
    const chosen = await findAvailablePort(48215, 5);
    expect(chosen).not.toBe(48215);
    expect(chosen).toBeGreaterThan(48215);
  });

  it('throws when nothing in range is free', async () => {
    holder = net.createServer();
    await new Promise<void>((resolve) => holder!.listen(48216, '127.0.0.1', () => resolve()));
    // range 0 means only the preferred port is checked, and it's held.
    await expect(findAvailablePort(48216, 0)).rejects.toThrow();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm run test -w force-app-desktop`
Expected: FAIL — `./port` has no exported member `isPortFree`.

- [ ] **Step 3: Implement**

Create `apps/force-app/desktop/src/port.ts`:

```ts
import net from 'node:net';

export function isPortFree(port: number, host = '127.0.0.1'): Promise<boolean> {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.once('error', () => resolve(false));
    srv.once('listening', () => srv.close(() => resolve(true)));
    srv.listen(port, host);
  });
}

/** Prefer `preferred`; otherwise scan upward through `range` candidate ports. A stale process
 * holding the default port must not wedge the app — see the sidecar spec's "Port" note. */
export async function findAvailablePort(preferred: number, range = 20): Promise<number> {
  if (await isPortFree(preferred)) return preferred;
  for (let p = preferred + 1; p <= preferred + range; p++) {
    if (await isPortFree(p)) return p;
  }
  throw new Error(`no free port found in [${preferred}, ${preferred + range}]`);
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npm run test -w force-app-desktop`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/force-app/desktop/src/port.ts apps/force-app/desktop/src/port.test.ts
git commit -m "feat(force-app-desktop): port resolver with fallback"
```

---

## Task 4: Custom `app://force` protocol handler

**Files:**
- Create: `apps/force-app/desktop/src/protocol.ts`
- Test: `apps/force-app/desktop/src/protocol.test.ts`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure path-resolution logic + a thin Electron-facing
  wrapper).
- Produces: `registerAppScheme(): void` (call before `app.whenReady`),
  `handleAppProtocol(webDistDir: string, configFilePath: string): void` (call after
  `app.whenReady`), and the testable pure function
  `resolveRequestPath(requestUrl, webDistDir, configFilePath): { filePath: string; is404: boolean }`.
  Task 7 wires `webDistDir()` to `apps/force-app/web/dist` (dev) or `resourcesPath/web` (packaged),
  and `configFilePath` to `ConfigStore.path` from Task 2.

- [ ] **Step 1: Write the failing tests**

Create `apps/force-app/desktop/src/protocol.test.ts`:

```ts
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { resolveRequestPath } from './protocol';

describe('resolveRequestPath', () => {
  let webDistDir: string;
  let configFilePath: string;

  beforeEach(() => {
    webDistDir = fs.mkdtempSync(path.join(os.tmpdir(), 'force-app-web-'));
    fs.writeFileSync(path.join(webDistDir, 'index.html'), '<html>spa</html>');
    fs.mkdirSync(path.join(webDistDir, 'assets'));
    fs.writeFileSync(path.join(webDistDir, 'assets', 'app.js'), 'console.log(1)');
    const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'force-app-userdata-'));
    configFilePath = path.join(userDataDir, 'config.json');
    fs.writeFileSync(configFilePath, '{"directusUrl":"https://example"}');
  });

  afterEach(() => {
    fs.rmSync(webDistDir, { recursive: true, force: true });
    fs.rmSync(path.dirname(configFilePath), { recursive: true, force: true });
  });

  it('serves index.html for the root path', () => {
    const { filePath, is404 } = resolveRequestPath('app://force/', webDistDir, configFilePath);
    expect(is404).toBe(false);
    expect(filePath).toBe(path.join(webDistDir, 'index.html'));
  });

  it('serves a hashed asset by exact path', () => {
    const { filePath, is404 } = resolveRequestPath('app://force/assets/app.js', webDistDir, configFilePath);
    expect(is404).toBe(false);
    expect(filePath).toBe(path.join(webDistDir, 'assets', 'app.js'));
  });

  it('serves config.json from userData rather than the bundled dist', () => {
    const { filePath, is404 } = resolveRequestPath('app://force/config.json', webDistDir, configFilePath);
    expect(is404).toBe(false);
    expect(filePath).toBe(configFilePath);
  });

  it('falls back to index.html for an unknown SPA route (history mode)', () => {
    const { filePath, is404 } = resolveRequestPath('app://force/settings', webDistDir, configFilePath);
    expect(is404).toBe(false);
    expect(filePath).toBe(path.join(webDistDir, 'index.html'));
  });

  it('rejects a request whose host is not "force"', () => {
    const { is404 } = resolveRequestPath('app://other/index.html', webDistDir, configFilePath);
    expect(is404).toBe(true);
  });

  it('blocks path traversal outside webDistDir', () => {
    const { is404 } = resolveRequestPath('app://force/..%2f..%2fsecrets.txt', webDistDir, configFilePath);
    expect(is404).toBe(true);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm run test -w force-app-desktop`
Expected: FAIL — `./protocol` has no exported member `resolveRequestPath`.

- [ ] **Step 3: Implement**

Create `apps/force-app/desktop/src/protocol.ts`:

```ts
import fs from 'node:fs';
import path from 'node:path';
import { net as electronNet, protocol } from 'electron';

export function registerAppScheme(): void {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: 'app',
      privileges: {
        standard: true,
        secure: true,
        corsEnabled: true,
        supportFetchAPI: true,
        stream: true,
      },
    },
  ]);
}

/** Maps an `app://force/<path>` request to the file that should serve it. A pure function so the
 * mapping is testable without booting Electron. `/config.json` is special-cased to userData
 * (Task 2's ConfigStore) rather than the bundled dist, because only that file can carry the
 * sidecar's actual resolved port. */
export function resolveRequestPath(
  requestUrl: string,
  webDistDir: string,
  configFilePath: string,
): { filePath: string; is404: boolean } {
  const u = new URL(requestUrl);
  if (u.hostname !== 'force') {
    return { filePath: '', is404: true };
  }
  let pathname = decodeURIComponent(u.pathname);
  if (pathname === '' || pathname === '/') pathname = '/index.html';

  if (pathname === '/config.json') {
    return { filePath: configFilePath, is404: !fs.existsSync(configFilePath) };
  }

  const root = path.normalize(webDistDir);
  const candidate = path.normalize(path.join(root, pathname));
  if (!candidate.startsWith(root)) {
    // Traversal guard: a request like app://force/..%2f..%2fsecrets must not escape webDistDir.
    return { filePath: '', is404: true };
  }
  if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
    return { filePath: candidate, is404: false };
  }
  // SPA history fallback: unknown sub-routes (e.g. /settings) resolve to index.html, matching
  // Caddy's `try_files {path} /index.html` for the /app/ surface.
  const indexPath = path.join(root, 'index.html');
  return { filePath: indexPath, is404: !fs.existsSync(indexPath) };
}

export function handleAppProtocol(webDistDir: string, configFilePath: string): void {
  protocol.handle('app', async (request) => {
    const { filePath, is404 } = resolveRequestPath(request.url, webDistDir, configFilePath);
    if (is404) return new Response('Not found', { status: 404 });
    return electronNet.fetch(`file://${filePath}`);
  });
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npm run test -w force-app-desktop`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/force-app/desktop/src/protocol.ts apps/force-app/desktop/src/protocol.test.ts
git commit -m "feat(force-app-desktop): app://force protocol handler"
```

---

## Task 5: Sidecar process supervisor

**Files:**
- Create: `apps/force-app/desktop/src/sidecar.ts`
- Create: `apps/force-app/desktop/src/__fixtures__/fake-backend.js`
- Test: `apps/force-app/desktop/src/sidecar.test.ts`

**Interfaces:**
- Produces: `SidecarSupervisor` (constructor `(opts: SidecarOptions)`), methods `start()`,
  `stop()`, `getState(): SidecarState`, `getPid(): number | null`, `getRestartCount(): number`,
  `lastDetail(): string | undefined`. Type `SidecarState = 'starting' | 'ready' | 'restarting' |
  'crashed' | 'stopped'`. `SidecarOptions` has `exePath`, `args`, `cwd?`, `port`, `healthUrl`,
  `readyTimeoutMs?`, `maxRestarts?`, `onStateChange?: (state, detail?) => void` — Task 7 supplies
  `exePath`/`args`/`cwd` from the dev-venv-vs-packaged-exe branch and `healthUrl` from Task 3's
  resolved port.

- [ ] **Step 1: Write the fixture backend**

Create `apps/force-app/desktop/src/__fixtures__/fake-backend.js`:

```js
// Minimal HTTP fixture standing in for the real recorder backend in sidecar tests.
// Args: <port> [--delay=<ms>]  (delay: how long /health returns 503 before flipping to 200)
const http = require('node:http');

const port = Number(process.argv[2]);
const delayArg = process.argv.find((a) => a.startsWith('--delay='));
const delayMs = delayArg ? Number(delayArg.split('=')[1]) : 0;
const startedAt = Date.now();

const server = http.createServer((req, res) => {
  if (req.url === '/health') {
    if (Date.now() - startedAt < delayMs) {
      res.writeHead(503).end();
      return;
    }
    res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify({ ok: true }));
    return;
  }
  res.writeHead(404).end();
});
server.listen(port);
```

- [ ] **Step 2: Write the failing tests**

Create `apps/force-app/desktop/src/sidecar.test.ts`:

```ts
import { describe, it, expect, afterEach } from 'vitest';
import path from 'node:path';
import { SidecarSupervisor, type SidecarState } from './sidecar';

const FIXTURE = path.join(__dirname, '__fixtures__', 'fake-backend.js');

function freePort(): number {
  // Test-only: a high random port. Real probing is covered by port.test.ts.
  return 39000 + Math.floor(Math.random() * 5000);
}

describe('SidecarSupervisor', () => {
  let sup: SidecarSupervisor | undefined;

  afterEach(async () => {
    await sup?.stop();
  });

  it('reaches ready once the fixture backend answers /health', async () => {
    const port = freePort();
    const states: SidecarState[] = [];
    sup = new SidecarSupervisor({
      exePath: process.execPath,
      args: [FIXTURE, String(port)],
      port,
      healthUrl: `http://127.0.0.1:${port}/health`,
      readyTimeoutMs: 5000,
      onStateChange: (s) => states.push(s),
    });
    await sup.start();
    expect(sup.getState()).toBe('ready');
    expect(states).toContain('starting');
    expect(states).toContain('ready');
  });

  it('reports crashed if the process never becomes healthy in time', async () => {
    const port = freePort();
    sup = new SidecarSupervisor({
      exePath: process.execPath,
      args: [FIXTURE, String(port), '--delay=999999'],
      port,
      healthUrl: `http://127.0.0.1:${port}/health`,
      readyTimeoutMs: 1000,
      maxRestarts: 0,
    });
    await sup.start();
    expect(sup.getState()).toBe('crashed');
  });

  it('restarts with backoff after the process dies, then gives up after maxRestarts', async () => {
    const port = freePort();
    const states: SidecarState[] = [];
    sup = new SidecarSupervisor({
      exePath: process.execPath,
      args: [FIXTURE, String(port)],
      port,
      healthUrl: `http://127.0.0.1:${port}/health`,
      readyTimeoutMs: 5000,
      maxRestarts: 1,
      onStateChange: (s) => states.push(s),
    });
    await sup.start();
    expect(sup.getState()).toBe('ready');

    // Simulate a crash: kill the process out from under the supervisor.
    process.kill(sup.getPid()!);
    await new Promise((r) => setTimeout(r, 3000));
    expect(sup.getState()).toBe('ready');
    expect(states).toContain('restarting');
    expect(sup.getRestartCount()).toBe(1);

    // A second crash exceeds maxRestarts=1 — the supervisor must give up rather than loop forever.
    process.kill(sup.getPid()!);
    await new Promise((r) => setTimeout(r, 4000));
    expect(sup.getState()).toBe('crashed');
  }, 15000);

  it('stop() terminates the process so a later health request fails', async () => {
    const port = freePort();
    sup = new SidecarSupervisor({
      exePath: process.execPath,
      args: [FIXTURE, String(port)],
      port,
      healthUrl: `http://127.0.0.1:${port}/health`,
      readyTimeoutMs: 5000,
    });
    await sup.start();
    expect(sup.getState()).toBe('ready');
    await sup.stop();
    await expect(
      fetch(`http://127.0.0.1:${port}/health`, { signal: AbortSignal.timeout(500) }),
    ).rejects.toThrow();
  });
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `npm run test -w force-app-desktop`
Expected: FAIL — `./sidecar` has no exported member `SidecarSupervisor`.

- [ ] **Step 4: Implement**

Create `apps/force-app/desktop/src/sidecar.ts`:

```ts
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
      void this.handleUnexpectedExit(`exit code=${code} signal=${signal}\n${stderrTail}`);
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
```

- [ ] **Step 5: Run to verify it passes**

Run: `npm run test -w force-app-desktop`
Expected: PASS (4 new tests; 14 total). The restart test runs ~7s of real backoff — that's
expected, not a hang.

- [ ] **Step 6: Commit**

```bash
git add apps/force-app/desktop/src/sidecar.ts apps/force-app/desktop/src/sidecar.test.ts apps/force-app/desktop/src/__fixtures__
git commit -m "feat(force-app-desktop): sidecar supervisor with health polling and backoff restart"
```

---

## Task 6: Window-open routing

**Files:**
- Create: `apps/force-app/desktop/src/windowOpen.ts`
- Test: `apps/force-app/desktop/src/windowOpen.test.ts`

**Interfaces:**
- Produces: `classifyWindowOpen(details: Electron.HandlerDetails): Electron.WindowOpenHandlerResponse`
  — pass directly as `webContents.setWindowOpenHandler(classifyWindowOpen)` in Task 7.

**Why this task exists:** `apps/force-app/web/src` calls `window.open()` in two shapes that must
be told apart in Electron — internal pop-out live-plot windows (`AppShell.vue`'s `openWindow`,
`ForcePanel.vue`, `FrmPanel.vue`, all via `appUrl()` on the app's own origin) versus
`StandaloneForceDashboard.vue`'s link to the Directus admin UI on a different origin entirely. The
former should open as a real Electron window on `app://force`; the latter should not open inside
Electron at all — it belongs in the system browser.

- [ ] **Step 1: Write the failing tests**

Create `apps/force-app/desktop/src/windowOpen.test.ts`:

```ts
import { describe, it, expect, vi } from 'vitest';

vi.mock('electron', () => ({ shell: { openExternal: vi.fn() } }));

import { shell } from 'electron';
import { classifyWindowOpen } from './windowOpen';

function details(url: string) {
  return { url } as Electron.HandlerDetails;
}

describe('classifyWindowOpen', () => {
  it('allows app://force URLs to open as a new Electron window', () => {
    const result = classifyWindowOpen(details('app://force/live/frm?x=1'));
    expect(result.action).toBe('allow');
    expect(shell.openExternal).not.toHaveBeenCalled();
  });

  it('routes an external Directus admin URL to the system browser and denies the Electron window', () => {
    const url = 'https://d1-server.tail54eeb6.ts.net/admin/content/x/1';
    const result = classifyWindowOpen(details(url));
    expect(result.action).toBe('deny');
    expect(shell.openExternal).toHaveBeenCalledWith(url);
  });

  it('denies an unparsable URL without throwing', () => {
    const result = classifyWindowOpen(details('not a url'));
    expect(result.action).toBe('deny');
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm run test -w force-app-desktop`
Expected: FAIL — `./windowOpen` has no exported member `classifyWindowOpen`.

- [ ] **Step 3: Implement**

Create `apps/force-app/desktop/src/windowOpen.ts`:

```ts
import { shell } from 'electron';

export function classifyWindowOpen(
  details: Electron.HandlerDetails,
): Electron.WindowOpenHandlerResponse {
  let url: URL;
  try {
    url = new URL(details.url);
  } catch {
    return { action: 'deny' };
  }
  if (url.protocol === 'app:' && url.hostname === 'force') {
    return {
      action: 'allow',
      overrideBrowserWindowOptions: {
        webPreferences: { contextIsolation: true, nodeIntegration: false },
      },
    };
  }
  void shell.openExternal(details.url);
  return { action: 'deny' };
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npm run test -w force-app-desktop`
Expected: PASS (3 new tests; 17 total)

- [ ] **Step 5: Commit**

```bash
git add apps/force-app/desktop/src/windowOpen.ts apps/force-app/desktop/src/windowOpen.test.ts
git commit -m "feat(force-app-desktop): route window.open between internal and external targets"
```

---

## Task 7: Main-process startup orchestration

**Files:**
- Modify: `apps/force-app/desktop/src/main.ts` (full rewrite of the body added in Task 1)

**Interfaces:**
- Consumes: `ConfigStore` (Task 2), `findAvailablePort` (Task 3), `registerAppScheme` /
  `handleAppProtocol` (Task 4), `SidecarSupervisor` (Task 5), `classifyWindowOpen` (Task 6).
- Produces: `getSupervisor(): SidecarSupervisor | null`, exported for Task 9 (recovery routing)
  and Task 14 (test hooks) to consume.

This task has no new unit tests of its own — it wires already-tested modules together, and the
wiring is verified end-to-end by running the app. Task 14 adds the automated Playwright coverage
for this flow once the pieces it needs (menu/preload, PyInstaller build) exist.

- [ ] **Step 1: Replace main.ts**

Modify `apps/force-app/desktop/src/main.ts` — replace the entire file:

```ts
import { app, BrowserWindow, dialog } from 'electron';
import path from 'node:path';
import { ConfigStore } from './config';
import { findAvailablePort } from './port';
import { registerAppScheme, handleAppProtocol } from './protocol';
import { SidecarSupervisor, type SidecarState } from './sidecar';
import { classifyWindowOpen } from './windowOpen';

const PREFERRED_PORT = 8200;
const HEALTH_PATH = '/health';

registerAppScheme();

let mainWindow: BrowserWindow | null = null;
let supervisor: SidecarSupervisor | null = null;

function webDistDir(): string {
  return app.isPackaged
    ? path.join(process.resourcesPath, 'web')
    : path.join(__dirname, '..', '..', 'web', 'dist');
}

function backendCommand(port: number): { exePath: string; args: string[]; cwd?: string } {
  if (app.isPackaged) {
    return {
      exePath: path.join(process.resourcesPath, 'backend', 'force-app-backend.exe'),
      args: ['--port', String(port)],
    };
  }
  // Dev mode: the same venv + uvicorn invocation apps/force-app/backend/scripts/start_recorder.ps1
  // uses, but bound to loopback only — the sidecar is reached solely by this app, on this machine.
  const backendDir = path.join(__dirname, '..', '..', 'backend');
  return {
    exePath: path.join(backendDir, '.venv', 'Scripts', 'python.exe'),
    args: ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port)],
    cwd: backendDir,
  };
}

function onSidecarStateChange(state: SidecarState, detail?: string): void {
  if (state === 'crashed') {
    dialog.showErrorBox('Recorder backend stopped responding', detail ?? 'See logs for details.');
  }
}

async function createWindow(): Promise<void> {
  const configStore = new ConfigStore(app.getPath('userData'));
  configStore.seedIfMissing();

  mainWindow = new BrowserWindow({
    width: 1500,
    height: 950,
    show: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  mainWindow.once('ready-to-show', () => mainWindow?.show());
  mainWindow.webContents.setWindowOpenHandler(classifyWindowOpen);

  handleAppProtocol(webDistDir(), configStore.path);
  await mainWindow.loadFile(path.join(__dirname, '..', 'static', 'loading.html'));

  const port = await findAvailablePort(PREFERRED_PORT);
  configStore.setRecorderPort(port);
  const cmd = backendCommand(port);

  supervisor = new SidecarSupervisor({
    exePath: cmd.exePath,
    args: cmd.args,
    cwd: cmd.cwd,
    port,
    healthUrl: `http://127.0.0.1:${port}${HEALTH_PATH}`,
    onStateChange: onSidecarStateChange,
  });
  await supervisor.start();

  if (supervisor.getState() !== 'ready') {
    dialog.showErrorBox(
      'Recorder backend failed to start',
      supervisor.lastDetail() ?? 'The backend did not become healthy in time.',
    );
    return;
  }

  await mainWindow.loadURL('app://force/');
}

export function getSupervisor(): SidecarSupervisor | null {
  return supervisor;
}

app.whenReady().then(() => {
  void createWindow();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', (event) => {
  if (!supervisor || supervisor.getState() === 'stopped') return;
  event.preventDefault();
  void supervisor.stop().then(() => app.quit());
});
```

- [ ] **Step 2: Typecheck**

Run: `npm run typecheck -w force-app-desktop`
Expected: no errors.

- [ ] **Step 3: Build the web SPA the desktop app will load**

```bash
npm run build:web
```

- [ ] **Step 4: Run and manually verify**

```bash
npm run dev -w force-app-desktop
```

Expected: the loading screen appears, then (once the local backend venv answers `/health`) the
window navigates to `app://force/` and shows the SPA's login page. Open DevTools
(`Ctrl+Shift+I`) and confirm the URL bar / `location.href` reads `app://force/login` (or
similar), not `file://…`.

**Known limitation at this point in the plan:** logging in will fail with a CORS error in the
DevTools console, because Directus's `CORS_ORIGIN` does not yet include `app://force` — that
deploy-side change is Task 12. Confirming the SPA *renders* under the new scheme is the goal of
this step; end-to-end login is verified after Task 12.

- [ ] **Step 5: Commit**

```bash
git add apps/force-app/desktop/src/main.ts
git commit -m "feat(force-app-desktop): wire config, port, protocol, sidecar and window-open into startup"
```

---

## Task 8: Preload bridge, application menu, and the Connectivity Doctor entry point

**Files:**
- Create: `apps/force-app/desktop/src/preload.ts`
- Create: `apps/force-app/desktop/src/menu.ts`
- Test: `apps/force-app/desktop/src/menu.test.ts`
- Modify: `apps/force-app/desktop/src/main.ts` (add preload path + application menu)
- Create: `apps/force-app/web/src/electronBridge.d.ts`
- Modify: `apps/force-app/web/src/router.ts` (listen for the `navigate` IPC message)
- Modify: `apps/force-app/web/src/settings/SettingsPage.vue` (initial tab from the route query)

**Interfaces:**
- Produces: a `navigate` IPC channel, main → renderer, carrying a router path string. Task 9
  reuses this same channel to route the operator to `/record` after a sidecar restart.

The spec calls for surfacing the existing Connectivity Doctor "from a desktop menu item, since
remote diagnosis on someone else's machine is the expected support mode." The doctor UI already
exists at `apps/force-app/web/src/settings/ConnectivitySettings.vue`, reached via
`SettingsPage.vue`'s local tab state — this task only needs to get the operator there, not build
new diagnostic UI.

- [ ] **Step 1: Write the failing test for the menu**

Create `apps/force-app/desktop/src/menu.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { vi } from 'vitest';

const sent: Array<[string, string]> = [];
const fakeWin = { webContents: { send: (channel: string, arg: string) => sent.push([channel, arg]) } };

vi.mock('electron', () => ({
  Menu: { buildFromTemplate: (template: unknown[]) => ({ template }) },
}));

import { buildMenu } from './menu';

describe('buildMenu', () => {
  it('the Connectivity Doctor item sends a navigate IPC message to the current window', () => {
    const menu = buildMenu(() => fakeWin as unknown as Electron.BrowserWindow) as unknown as {
      template: Array<{ label: string; submenu: Array<{ label: string; click: () => void }> }>;
    };
    const help = menu.template.find((m) => m.label === 'Help')!;
    const doctor = help.submenu.find((m) => m.label === 'Connectivity Doctor')!;
    doctor.click();
    expect(sent).toEqual([['navigate', '/settings?tab=connectivity']]);
  });

  it('does nothing when there is no current window', () => {
    const menu = buildMenu(() => null) as unknown as {
      template: Array<{ label: string; submenu: Array<{ label: string; click: () => void }> }>;
    };
    const help = menu.template.find((m) => m.label === 'Help')!;
    const doctor = help.submenu.find((m) => m.label === 'Connectivity Doctor')!;
    expect(() => doctor.click()).not.toThrow();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm run test -w force-app-desktop`
Expected: FAIL — `./menu` has no exported member `buildMenu`.

- [ ] **Step 3: Implement the menu**

Create `apps/force-app/desktop/src/menu.ts`:

```ts
import { Menu } from 'electron';

export function buildMenu(getWindow: () => Electron.BrowserWindow | null): Electron.Menu {
  return Menu.buildFromTemplate([
    {
      label: 'View',
      submenu: [{ role: 'reload' }, { role: 'toggleDevTools' }],
    },
    {
      label: 'Help',
      submenu: [
        {
          label: 'Connectivity Doctor',
          click: () => {
            getWindow()?.webContents.send('navigate', '/settings?tab=connectivity');
          },
        },
      ],
    },
  ]);
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npm run test -w force-app-desktop`
Expected: PASS (2 new tests; 19 total)

- [ ] **Step 5: Implement the preload bridge**

Create `apps/force-app/desktop/src/preload.ts`:

```ts
import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('forceApp', {
  onNavigate: (callback: (path: string) => void) => {
    ipcRenderer.on('navigate', (_event, targetPath: string) => callback(targetPath));
  },
});
```

- [ ] **Step 6: Wire the preload path and menu into main.ts**

Modify `apps/force-app/desktop/src/main.ts`:

Add to the imports:

```ts
import { app, BrowserWindow, dialog, Menu } from 'electron';
```

(replacing the existing `import { app, BrowserWindow, dialog } from 'electron';` line)

Add below the other imports:

```ts
import { buildMenu } from './menu';
```

In `createWindow()`, add `preload` to the `BrowserWindow` constructor's `webPreferences`:

```ts
  mainWindow = new BrowserWindow({
    width: 1500,
    height: 950,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload.js'),
    },
  });
```

And set the application menu once, right after the two module-level `let` declarations (placed
after them, not before, so the closure below reads cleanly next to the variable it captures):

```ts
let mainWindow: BrowserWindow | null = null;
let supervisor: SidecarSupervisor | null = null;
Menu.setApplicationMenu(buildMenu(() => mainWindow));
```

- [ ] **Step 7: Add the renderer-side type declaration**

Create `apps/force-app/web/src/electronBridge.d.ts`:

```ts
// Ambient type for the bridge apps/force-app/desktop/src/preload.ts exposes. `window.forceApp` is
// only present when the SPA runs inside the Electron shell — the same bundle also serves the
// read-only /app/ browser surface (infra/caddy/Caddyfile), where it is undefined.
export {};

declare global {
  interface Window {
    forceApp?: {
      onNavigate: (callback: (path: string) => void) => void;
    };
  }
}
```

- [ ] **Step 8: Listen for the navigate IPC in the router**

Modify `apps/force-app/web/src/router.ts` — add after the `router.beforeEach(...)` block:

```ts
// Electron desktop shell only (see electronBridge.d.ts): the main process's Help menu and the
// sidecar-recovery flow (apps/force-app/desktop/src/sidecar.ts) both route the renderer here.
if (window.forceApp) {
  window.forceApp.onNavigate((targetPath) => {
    void router.push(targetPath);
  });
}
```

- [ ] **Step 9: Read the initial Settings tab from the route query**

Modify `apps/force-app/web/src/settings/SettingsPage.vue` — in the `<script setup>` block, replace:

```ts
const active = ref<'general' | 'alarms' | 'connectivity' | 'backup'>('general');
```

with:

```ts
import { useRoute } from 'vue-router';

const VALID_TABS = ['general', 'alarms', 'connectivity', 'backup'] as const;
type SettingsTab = (typeof VALID_TABS)[number];

const route = useRoute();
const requestedTab = route.query.tab as string | undefined;
const initialTab: SettingsTab = VALID_TABS.includes(requestedTab as SettingsTab)
	? (requestedTab as SettingsTab)
	: 'general';
const active = ref<SettingsTab>(initialTab);
```

(`ref` is already imported at the top of the file; add the `useRoute` import alongside it.)

- [ ] **Step 10: Typecheck both workspaces**

```bash
npm run typecheck -w force-app-desktop
npm run typecheck -w force-app-web
```

Expected: no errors in either.

- [ ] **Step 11: Manual verification**

```bash
npm run build -w force-app-desktop
npm run build:web
npm run dev -w force-app-desktop
```

Log in (Directus CORS still blocks this until Task 12 — if it fails, open DevTools and confirm
the *only* error is the expected CORS failure, not a preload/menu error). Open DevTools Console
and run:

```js
window.forceApp.onNavigate((p) => console.log('navigated to', p));
```

Then click **Help > Connectivity Doctor** from the menu bar. Expected: the console logs
`navigated to /settings?tab=connectivity` and the Settings page opens with the Connectivity tab
already selected.

- [ ] **Step 12: Commit**

```bash
git add apps/force-app/desktop/src/preload.ts apps/force-app/desktop/src/menu.ts apps/force-app/desktop/src/menu.test.ts apps/force-app/desktop/src/main.ts apps/force-app/web/src/electronBridge.d.ts apps/force-app/web/src/router.ts apps/force-app/web/src/settings/SettingsPage.vue
git commit -m "feat(force-app-desktop): preload bridge, menu, and Connectivity Doctor entry point"
```

---

## Task 9: Recovery-check routing and scheduled-task cleanup

**Files:**
- Create: `apps/force-app/desktop/src/scheduledTask.ts`
- Test: `apps/force-app/desktop/src/scheduledTask.test.ts`
- Modify: `apps/force-app/desktop/src/sidecar.ts` (already exposes `getRestartCount()` — no change
  needed; confirmed by Task 5)
- Modify: `apps/force-app/desktop/src/main.ts` (route to `/record` after a restart; offer cleanup
  after first successful start)

**Interfaces:**
- Produces: `offerScheduledTaskCleanup(deps?: ScheduledTaskDeps): Promise<void>`, with
  `ScheduledTaskDeps = { taskExists, removeTask, confirm }` injectable for testing and
  `makeDefaultDeps()` wiring the real `schtasks`/`dialog` calls.

The spec requires two related but distinct behaviors: (1) after any sidecar restart, surface the
existing `/recovery/check` UI (already built into `RecordPage.vue` — see
`apps/force-app/web/src/record/RecordPage.vue:159-167`), and (2) on first run, offer to remove the
old `ForceAppRecorderBackend` scheduled task so it can't contend for the port with the app's own
sidecar.

- [ ] **Step 1: Write the failing tests**

Create `apps/force-app/desktop/src/scheduledTask.test.ts`:

```ts
import { describe, it, expect, vi } from 'vitest';
import { offerScheduledTaskCleanup, type ScheduledTaskDeps } from './scheduledTask';

describe('offerScheduledTaskCleanup', () => {
  it('does nothing when the old task is not present', async () => {
    const deps: ScheduledTaskDeps = {
      taskExists: vi.fn().mockResolvedValue(false),
      removeTask: vi.fn().mockResolvedValue(undefined),
      confirm: vi.fn().mockResolvedValue(true),
    };
    await offerScheduledTaskCleanup(deps);
    expect(deps.confirm).not.toHaveBeenCalled();
    expect(deps.removeTask).not.toHaveBeenCalled();
  });

  it('removes the task when the user confirms', async () => {
    const deps: ScheduledTaskDeps = {
      taskExists: vi.fn().mockResolvedValue(true),
      removeTask: vi.fn().mockResolvedValue(undefined),
      confirm: vi.fn().mockResolvedValue(true),
    };
    await offerScheduledTaskCleanup(deps);
    expect(deps.removeTask).toHaveBeenCalledOnce();
  });

  it('leaves the task in place when the user declines', async () => {
    const deps: ScheduledTaskDeps = {
      taskExists: vi.fn().mockResolvedValue(true),
      removeTask: vi.fn().mockResolvedValue(undefined),
      confirm: vi.fn().mockResolvedValue(false),
    };
    await offerScheduledTaskCleanup(deps);
    expect(deps.removeTask).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm run test -w force-app-desktop`
Expected: FAIL — `./scheduledTask` has no exported member `offerScheduledTaskCleanup`.

- [ ] **Step 3: Implement**

Create `apps/force-app/desktop/src/scheduledTask.ts`:

```ts
import { execFile } from 'node:child_process';
import { dialog } from 'electron';

const TASK_NAME = 'ForceAppRecorderBackend';

export interface ScheduledTaskDeps {
  taskExists: () => Promise<boolean>;
  removeTask: () => Promise<void>;
  confirm: () => Promise<boolean>;
}

export function makeDefaultDeps(): ScheduledTaskDeps {
  return {
    taskExists: () =>
      new Promise((resolve) => {
        execFile('schtasks', ['/query', '/tn', TASK_NAME], (error) => resolve(!error));
      }),
    removeTask: () =>
      new Promise((resolve) => {
        execFile('schtasks', ['/delete', '/tn', TASK_NAME, '/f'], () => resolve());
      }),
    confirm: async () => {
      const { response } = await dialog.showMessageBox({
        type: 'question',
        buttons: ['Remove it', 'Leave it for now'],
        defaultId: 0,
        title: 'Old auto-start task found',
        message:
          `The scheduled task "${TASK_NAME}" starts the old recorder backend automatically. ` +
          'This app now manages the backend itself — leaving the old task running would let ' +
          'both compete for the same port. Remove it?',
      });
      return response === 0;
    },
  };
}

/** Offers to remove the pre-Electron auto-start task the first time it's found running. See
 * apps/force-app/backend/scripts/install_autostart.ps1 for what it does. */
export async function offerScheduledTaskCleanup(deps: ScheduledTaskDeps = makeDefaultDeps()): Promise<void> {
  if (!(await deps.taskExists())) return;
  if (await deps.confirm()) await deps.removeTask();
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npm run test -w force-app-desktop`
Expected: PASS (3 new tests; 22 total)

- [ ] **Step 5: Wire both behaviors into main.ts**

Modify `apps/force-app/desktop/src/main.ts`:

Add to the imports:

```ts
import { offerScheduledTaskCleanup } from './scheduledTask';
```

Replace `onSidecarStateChange`:

```ts
function onSidecarStateChange(state: SidecarState, detail?: string): void {
  if (state === 'crashed') {
    dialog.showErrorBox('Recorder backend stopped responding', detail ?? 'See logs for details.');
  }
  // A restart (not the initial start) means the backend crashed mid-session — route the
  // operator back to Record, where the existing recovery banner (RecordPage.vue) picks up any
  // incomplete session via GET /recovery/check on mount.
  if (state === 'ready' && supervisor && supervisor.getRestartCount() > 0) {
    mainWindow?.webContents.send('navigate', '/record');
  }
}
```

At the end of `createWindow()`, after `await mainWindow.loadURL('app://force/');`, add:

```ts
  void offerScheduledTaskCleanup();
```

- [ ] **Step 6: Typecheck**

Run: `npm run typecheck -w force-app-desktop`
Expected: no errors.

- [ ] **Step 7: Manual verification**

```bash
npm run build -w force-app-desktop
npm run dev -w force-app-desktop
```

If the old scheduled task exists on this machine (`schtasks /query /tn ForceAppRecorderBackend`),
confirm the dialog appears after the window loads and both button choices behave as expected
(check with `schtasks /query /tn ForceAppRecorderBackend` again afterward). If the task does not
exist here, this step is confirmed instead by the unit tests from Step 4 — note that in the task
report rather than fabricating a dialog interaction that can't happen on this machine.

- [ ] **Step 8: Commit**

```bash
git add apps/force-app/desktop/src/scheduledTask.ts apps/force-app/desktop/src/scheduledTask.test.ts apps/force-app/desktop/src/main.ts
git commit -m "feat(force-app-desktop): route to Record after a sidecar restart, offer to remove the old scheduled task"
```

---

## Task 10: PyInstaller backend packaging

**Files:**
- Create: `apps/force-app/backend/run_frozen.py`
- Create: `apps/force-app/backend/force-app-backend.spec`
- Create: `apps/force-app/backend/scripts/build_frozen.ps1`
- Modify: `apps/force-app/backend/pyproject.toml` (add a `build` optional-dependency group)
- Modify: `apps/force-app/backend/app/main.py` (surface missing NI-DAQmx in the Connectivity
  Doctor, per the design spec's risk note)
- Modify: `apps/force-app/backend/tests/test_resiliency_api.py` (cover the new finding)

**Interfaces:**
- Produces: `apps/force-app/backend/dist/force-app-backend/force-app-backend.exe`, invoked as
  `force-app-backend.exe --port <n>`, binding `127.0.0.1:<n>` — the packaged-mode command Task 7's
  `backendCommand()` already targets at `resourcesPath/backend/force-app-backend.exe`.

**Why this task also touches `main.py`:** the design spec's Risks section requires that "the
installer must detect [the NI-DAQmx runtime's] absence and say so clearly rather than failing at
first recording." Today `nidaq_available()` (`app/sources/nidaq.py`) is only consulted reactively,
inside `POST /record/start` — nothing surfaces it proactively. `GET /health/doctor` (the backing
endpoint for the Connectivity Doctor Task 8 already wired into the desktop menu) is the existing,
correct place for a proactive, non-blocking finding: it already has an ok/warn/fail findings list
covering Internet, Directus, LabAmp, disk space, and crashed recordings, so this is one more
finding in an established pattern rather than new UI.

- [ ] **Step 1: Add the frozen entry point**

The existing dev launch (`start_recorder.ps1`) shells out to the `uvicorn` CLI, which does not
exist inside a frozen bundle. Create `apps/force-app/backend/run_frozen.py`:

```python
"""Entry point for the PyInstaller-frozen backend. The Electron sidecar (apps/force-app/desktop)
spawns the frozen exe with `--port <n>`; this runs uvicorn in-process rather than shelling out to
the `uvicorn` CLI (which isn't present inside a frozen bundle), bound to loopback only — the
sidecar is reached solely by the Electron renderer on the same machine.
"""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8200)
    args = parser.parse_args()
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Add the `build` optional-dependency group**

Modify `apps/force-app/backend/pyproject.toml` — add after the existing `nidaq` extra:

```toml
# PyInstaller freeze (Electron packaging). Kept out of the base install — only needed when
# building the desktop app's sidecar, not for day-to-day backend development.
build = ["pyinstaller>=6.10"]
```

- [ ] **Step 3: Write the PyInstaller spec**

Create `apps/force-app/backend/force-app-backend.spec`:

```python
# PyInstaller spec for the frozen recorder backend. One-folder mode (not --onefile): a one-file
# build re-extracts ~200 MB of scipy/numpy to a temp dir on every launch, which is slow and a
# reliable antivirus trigger — see
# docs/superpowers/specs/2026-08-10-force-app-desktop-packaging-design.md.
#
# Build with: pyinstaller force-app-backend.spec --noconfirm

from PyInstaller.utils.hooks import collect_submodules

hidden_imports = collect_submodules("uvicorn") + collect_submodules("scipy")

# nidaqmx is only installed on the acquisition machine (`pip install -e ".[nidaq]"`); don't force
# it as a hidden import on a build machine that doesn't have it.
try:
    import nidaqmx  # noqa: F401

    hidden_imports.append("nidaqmx")
except ImportError:
    pass

a = Analysis(
    ["run_frozen.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="force-app-backend",
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="force-app-backend",
)
```

- [ ] **Step 4: Write the build script**

Create `apps/force-app/backend/scripts/build_frozen.ps1`:

```powershell
# Freezes the recorder backend into a one-folder PyInstaller bundle at
# apps\force-app\backend\dist\force-app-backend\. Run from the backend's own venv so the frozen
# build picks up whatever is installed there (including the nidaqmx extra, if the venv has it).
#
# Run:
#   powershell -ExecutionPolicy Bypass -File .\scripts\build_frozen.ps1

$ErrorActionPreference = 'Stop'
$BackendDir = Split-Path -Parent $PSScriptRoot
Push-Location $BackendDir
try {
    if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
        Write-Host "pyinstaller not found on PATH - installing the [build] extra..."
        pip install -e ".[build]"
    }
    pyinstaller force-app-backend.spec --noconfirm
    Write-Host "Built: $BackendDir\dist\force-app-backend\force-app-backend.exe"
} finally {
    Pop-Location
}
```

- [ ] **Step 5: Add the NI-DAQ runtime finding to the Connectivity Doctor**

Modify `apps/force-app/backend/app/main.py` — add an import near the top, alongside the existing
`from . import nidaq_catalog, nidaq_enum, recovery, storage` line:

```python
from .sources.nidaq import nidaq_available
```

Then, inside `health_doctor()`, add a new finding. Insert it after the existing `# 4. LabAmp`
block and before `# 5. Filter service & Octree server`, renumbering the later comments (`5.` →
`6.`, the two existing `6.`s → `7.`/`8.`) so they stay in order:

```python
    # 5. NI-DAQ runtime — checked proactively so a missing driver is visible before the operator
    # tries to record, not discovered as a 503 from POST /record/start.
    if nidaq_available():
        findings.append({"service": "NI-DAQ runtime", "status": "ok", "message": "NI-DAQmx driver detected"})
    else:
        findings.append({
            "service": "NI-DAQ runtime", "status": "warn",
            "message": "NI-DAQmx runtime not found on this machine",
            "diagnosis": "Real hardware recording is unavailable. This is expected on a "
                         "non-acquisition machine (sim/replay sources still work); if this IS "
                         "the acquisition PC, the NI-DAQmx driver needs installing.",
            "fix": "Install the NI-DAQmx runtime from ni.com, then restart the app.",
        })
```

- [ ] **Step 6: Write the test**

Modify `apps/force-app/backend/tests/test_resiliency_api.py` — add a new test near the existing
`/health/doctor`-adjacent tests (search the file for `health/doctor` to find them; if none exist
yet, add this test at the end of the file):

```python
def test_health_doctor_reports_nidaq_runtime_status():
    with TestClient(fastapi_app) as client:
        r = client.post("/health/doctor", json={})
        assert r.status_code == 200, r.text
        findings = r.json()["findings"]
        nidaq = next(f for f in findings if f["service"] == "NI-DAQ runtime")
        # This test environment has no NI-DAQmx driver installed, so the finding must warn, not
        # silently pass as "ok" — that's the whole point of the check.
        assert nidaq["status"] == "warn"
        assert "NI-DAQmx" in nidaq["message"]
```

Run: `cd apps/force-app/backend && .venv\Scripts\pytest tests/test_resiliency_api.py -k nidaq_runtime -v`
Expected: PASS.

- [ ] **Step 7: Run the full backend test suite**

```powershell
cd apps\force-app\backend
.venv\Scripts\pytest
```

Expected: all tests pass (the new one plus the existing suite, unaffected by this change).

- [ ] **Step 8: Build and manually verify the frozen exe**

```powershell
cd apps\force-app\backend
.venv\Scripts\Activate.ps1
pip install -e ".[build]"
.\scripts\build_frozen.ps1
.\dist\force-app-backend\force-app-backend.exe --port 8291
```

In a second terminal:

```powershell
curl http://127.0.0.1:8291/health
curl -Method POST http://127.0.0.1:8291/health/doctor
```

Expected: `/health` returns `{"ok":true,"state":"idle"}`; `/health/doctor`'s findings include the
new `"NI-DAQ runtime"` entry with `"status":"warn"` (this build machine has no NI-DAQmx driver).
Stop the exe with `Ctrl+C` in the first terminal.

- [ ] **Step 9: Commit**

```bash
git add apps/force-app/backend/run_frozen.py apps/force-app/backend/force-app-backend.spec apps/force-app/backend/scripts/build_frozen.ps1 apps/force-app/backend/pyproject.toml apps/force-app/backend/app/main.py apps/force-app/backend/tests/test_resiliency_api.py
git commit -m "feat(force-app-backend): PyInstaller one-folder freeze; surface missing NI-DAQmx runtime in the Connectivity Doctor"
```

---

## Task 11: `electron-builder` packaging config and `electron-updater` wiring

**Files:**
- Create: `apps/force-app/desktop/electron-builder.yml`
- Create: `apps/force-app/desktop/src/updater.ts`
- Modify: `apps/force-app/desktop/package.json` (add `electron-builder`, `electron-updater`, and a
  `package` script)
- Modify: `apps/force-app/desktop/src/main.ts` (call `initAutoUpdater()`)

**Interfaces:**
- Consumes: `apps/force-app/web/dist` (built by Task 7's manual step) and
  `apps/force-app/backend/dist/force-app-backend` (built by Task 10) as `extraResources`.
- Produces: `apps/force-app/desktop/release/*.exe` + `latest.yml`, and `initAutoUpdater(): void`.

- [ ] **Step 1: Add dependencies and the package script**

Modify `apps/force-app/desktop/package.json`:

Add to `"scripts"`:

```json
    "package": "npm run build && electron-builder --win"
```

Add `electron-updater` to `"dependencies"` (it runs at app runtime, not just build time):

```json
  "dependencies": {
    "electron-updater": "^6.3.0"
  },
```

Add `electron-builder` to `"devDependencies"`:

```json
    "electron-builder": "^25.1.0",
```

Then run:

```bash
npm install -w force-app-desktop
```

- [ ] **Step 2: Write the builder config**

Create `apps/force-app/desktop/electron-builder.yml`:

```yaml
# Electron packaging config. Unsigned (v1 — see ADR-0010's open decisions) and the update feed is
# Tailscale-only; both are documented, coupled decisions — do not point `publish.url` at a public
# host without re-reading docs/superpowers/specs/2026-08-10-force-app-desktop-packaging-design.md.
appId: net.tailscale.d1-server.force-app
productName: Force App
directories:
  output: release
files:
  - dist/**/*
  - static/**/*
  - package.json
extraResources:
  - from: ../web/dist
    to: web
  - from: ../backend/dist/force-app-backend
    to: backend
win:
  target: nsis
  artifactName: '${productName}-Setup-${version}.${ext}'
nsis:
  oneClick: false
  allowToChangeInstallationDirectory: true
  createDesktopShortcut: true
publish:
  - provider: generic
    url: https://d1-server.tail54eeb6.ts.net/force-app-updates/
    channel: latest
```

- [ ] **Step 3: Implement the updater wiring**

Create `apps/force-app/desktop/src/updater.ts`:

```ts
import { app, dialog } from 'electron';
import { autoUpdater } from 'electron-updater';

/** electron-updater needs a real packaged app with publish config to do anything meaningful —
 * calling it in dev throws on the missing dev-update-config.yml, so this is a no-op there. */
export function initAutoUpdater(): void {
  if (!app.isPackaged) return;

  autoUpdater.autoDownload = true;
  autoUpdater.on('update-downloaded', () => {
    void dialog
      .showMessageBox({
        type: 'info',
        buttons: ['Restart now', 'Later'],
        defaultId: 0,
        title: 'Update ready',
        message: 'An update has been downloaded. Restart to apply it?',
      })
      .then(({ response }) => {
        if (response === 0) autoUpdater.quitAndInstall();
      });
  });
  autoUpdater.on('error', (err) => {
    console.error('autoUpdater error', err);
  });
  autoUpdater.checkForUpdates().catch((err) => console.error('checkForUpdates failed', err));
}
```

- [ ] **Step 4: Wire it into main.ts**

Modify `apps/force-app/desktop/src/main.ts`:

Add to the imports:

```ts
import { initAutoUpdater } from './updater';
```

At the end of `createWindow()`, after `void offerScheduledTaskCleanup();`, add:

```ts
  initAutoUpdater();
```

- [ ] **Step 5: Typecheck**

Run: `npm run typecheck -w force-app-desktop`
Expected: no errors.

- [ ] **Step 6: Build the installer and manually verify**

```bash
npm run build:web
npm run build -w force-app-backend --if-present 2>$null; cd apps/force-app/backend; .venv\Scripts\Activate.ps1; pip install -e ".[build]"; .\scripts\build_frozen.ps1; cd ../../..
npm run package -w force-app-desktop
```

Expected: `apps/force-app/desktop/release/Force App-Setup-0.1.0.exe` and
`apps/force-app/desktop/release/latest.yml` both exist. Run the installer, launch the app, confirm
the window opens and loads the SPA (login will still fail on CORS until Task 12 — that's
expected).

Note: `initAutoUpdater()`'s actual update-detection behavior (finding and downloading a newer
version from the feed) cannot be verified until Task 13 has published a real release to the feed.
This step only confirms the packaged build launches; the full update cycle is a deferred manual
check at first real release, not something this plan can test in isolation.

- [ ] **Step 7: Commit**

```bash
git add apps/force-app/desktop/package.json apps/force-app/desktop/package-lock.json apps/force-app/desktop/electron-builder.yml apps/force-app/desktop/src/updater.ts apps/force-app/desktop/src/main.ts
git commit -m "feat(force-app-desktop): electron-builder packaging and electron-updater wiring"
```

---

## Task 12: Deploy-side changes — CORS origin and the update feed route

**Files:**
- Modify: `.env.example` (document `app://force` in `FORCE_APP_ORIGIN`)
- Modify: `infra/caddy/Caddyfile` (serve the update feed)
- Modify: `docker-compose.yml` (mount the feed directory)
- Modify: `.gitignore` (the feed directory holds built binaries, never git)
- Create: `apps/force-app/desktop/scripts/publish-release.ps1` (run on `d1-server`)

This is the task that makes Task 7's "known limitation" (CORS blocking login) and Task 11's
"update-detection unverifiable" go away — both require live changes on `d1-server`, which this
plan documents but cannot execute from here (no access to that host in this session).

- [ ] **Step 1: Document the new CORS origin**

Modify `.env.example` — replace:

```
# Origin of the standalone force-app SPA (apps/force-app/web). Directus CORS_ORIGIN
# and the filter-service CORS allow-list are set to this so the SPA can call them
# cross-origin with Bearer tokens. Match your dev/prod SPA host + port.
FORCE_APP_ORIGIN=http://localhost:5180
```

with:

```
# Origins allowed to call Directus and the filter-service cross-origin with Bearer tokens:
# the browser dev server, and (once ADR-0010 steps 3-4 are deployed) the Electron desktop app's
# app://force origin. Comma-separate, no spaces — see
# docs/superpowers/specs/2026-08-10-force-app-desktop-packaging-design.md.
FORCE_APP_ORIGIN=http://localhost:5180,app://force
```

- [ ] **Step 2: Add the feed directory to .gitignore**

Modify `.gitignore` — add under the "Build / tooling output" section, alongside the existing
`infra/octrees` line:

```
infra/force-app-updates
```

- [ ] **Step 3: Mount the feed directory in docker-compose.yml**

Modify `docker-compose.yml` — in the `caddy` service's `volumes:` list, add a line alongside the
existing `./infra/octrees:/srv/octrees:ro` mount:

```yaml
      - ./infra/force-app-updates:/srv/force-app-updates:ro   # Electron auto-update feed
```

- [ ] **Step 4: Serve the feed from Caddy**

Modify `infra/caddy/Caddyfile` — add a new `handle_path` block, alongside the existing
`/octrees/*` block:

```
    # Electron auto-update feed (electron-updater, generic provider). Populated by a pull-based
    # publish script run on this host (apps/force-app/desktop/scripts/publish-release.ps1) — see
    # docs/superpowers/specs/2026-08-10-force-app-desktop-packaging-design.md. Tailnet-only by
    # construction: this Caddy instance is reachable only over Tailscale, and the app ships
    # unsigned, so the update channel's trust rests entirely on this transport staying private.
    handle_path /force-app-updates/* {
        root * /srv/force-app-updates
        file_server
    }
```

- [ ] **Step 5: Write the publish script**

Create `apps/force-app/desktop/scripts/publish-release.ps1`:

```powershell
# Run on d1-server after a `force-app-v*` tag's CI build finishes. Pulls that release's installer
# + latest.yml from GitHub (d1-server has outbound internet; this avoids putting a
# tailnet-reaching credential in GitHub Actions secrets) and drops them into the Caddy-served
# update feed at infra/force-app-updates/. electron-updater needs BOTH files present — the
# installer without latest.yml is invisible to clients.
#
# Requires: `gh auth login` has been run once on this machine.
#
# Run:
#   powershell -ExecutionPolicy Bypass -File .\publish-release.ps1 -Tag force-app-v0.1.0

param(
    [Parameter(Mandatory = $true)][string]$Tag,
    [string]$Repo = 'dpremoli/D1-Database'
)
$ErrorActionPreference = 'Stop'

$ScriptDir = $PSScriptRoot
$RepoRoot = (Get-Item $ScriptDir).Parent.Parent.Parent.Parent.FullName
$FeedDir = Join-Path $RepoRoot 'infra\force-app-updates'

New-Item -ItemType Directory -Force -Path $FeedDir | Out-Null

Write-Host "Fetching release assets for $Tag from $Repo..."
gh release download $Tag --repo $Repo --dir $FeedDir --clobber
if ($LASTEXITCODE -ne 0) { throw "gh release download failed (exit $LASTEXITCODE)." }

$latestYml = Join-Path $FeedDir 'latest.yml'
if (-not (Test-Path $latestYml)) {
    throw "latest.yml is missing from the downloaded assets - electron-updater will not see this release."
}

Write-Host "Published $Tag to $FeedDir"
Get-ChildItem $FeedDir | Format-Table Name, Length, LastWriteTime
```

- [ ] **Step 6: Document the manual deploy step**

These changes are safe to commit, but three of them only take effect once someone with access to
`d1-server` acts on them — note this explicitly rather than implying the commit alone is
sufficient:

1. Update the live `.env` on `d1-server`: change `FORCE_APP_ORIGIN` to
   `http://localhost:5180,app://force`, then `docker compose up -d directus filter-service` to
   pick it up.
2. `docker compose up -d caddy` to mount the new `infra/force-app-updates` volume and pick up the
   updated `Caddyfile`.
3. Run `gh auth login` once on `d1-server` if it hasn't been done already, so
   `publish-release.ps1` (Task 13 uses it) can authenticate.

- [ ] **Step 7: Commit**

```bash
git add .env.example .gitignore infra/caddy/Caddyfile docker-compose.yml apps/force-app/desktop/scripts/publish-release.ps1
git commit -m "feat(infra): CORS origin and update feed route for the Electron desktop app"
```

---

## Task 13: CI workflow

**Files:**
- Create: `.github/workflows/force-app-release.yml`

**Interfaces:**
- Consumes: every workspace script defined in Tasks 1–11 (`npm run build:web`,
  `.venv\Scripts\pytest`, `pyinstaller force-app-backend.spec`, `npm test -w force-app-desktop`,
  `npm run package -w force-app-desktop`).

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/force-app-release.yml`:

```yaml
name: force-app-release

on:
  push:
    tags:
      - 'force-app-v*'
    paths:
      - 'apps/force-app/**'
      - 'packages/force-plotting/**'

jobs:
  build:
    runs-on: windows-latest
    defaults:
      run:
        shell: pwsh
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: '24'

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install JS workspace dependencies
        run: npm ci

      - name: Build the web SPA
        run: npm run build:web

      - name: Install backend dependencies
        working-directory: apps/force-app/backend
        run: |
          python -m venv .venv
          .venv\Scripts\pip install -e ".[build]"

      - name: Run backend tests
        working-directory: apps/force-app/backend
        run: .venv\Scripts\pytest

      - name: Freeze the backend with PyInstaller
        working-directory: apps/force-app/backend
        run: .venv\Scripts\pyinstaller force-app-backend.spec --noconfirm

      - name: Run desktop unit tests
        working-directory: apps/force-app/desktop
        run: npm test

      - name: Build the Electron installer
        working-directory: apps/force-app/desktop
        run: |
          npm run build
          npx electron-builder --win --publish never

      - name: Upload installer artifact
        uses: actions/upload-artifact@v4
        with:
          name: force-app-installer
          path: |
            apps/force-app/desktop/release/*.exe
            apps/force-app/desktop/release/latest.yml
```

`--publish never` is deliberate: CI builds and uploads a workflow artifact only. Publishing to the
feed is the separate pull-based step (`publish-release.ps1`, Task 12) run manually on `d1-server`
— CI cannot reach that host, which is the whole point of it being tailnet-only.

- [ ] **Step 2: Validate the YAML**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/force-app-release.yml'))"
```

Expected: no output (parses cleanly). This only checks syntax — the workflow itself is exercised
for real the first time a `force-app-v*` tag is pushed, which is outside this plan's scope (no tag
has been agreed with the user).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/force-app-release.yml
git commit -m "ci(force-app): build and package the Electron installer on force-app-v* tags"
```

---

## Task 14: Playwright smoke tests

**Files:**
- Create: `apps/force-app/desktop/playwright.config.ts`
- Create: `apps/force-app/desktop/tests/smoke.spec.ts`
- Modify: `apps/force-app/desktop/package.json` (add `@playwright/test`, a `test:e2e` script)
- Modify: `apps/force-app/desktop/src/main.ts` (test-only hook, gated behind an env var)

**Interfaces:**
- Consumes: `getSupervisor()` from Task 7, via a test-only hook attached to `global` — Playwright's
  `_electron` API can only reach the main process through `app.evaluate()`, which has no access to
  `main.ts`'s module-level exports otherwise.

These are the two tests the design spec calls out explicitly: a packaged-app boot smoke test ("the
test that would catch a broken bundle, which unit tests cannot") and a sidecar-supervision test
(kill the backend, confirm the app recovers). Both launch the compiled `dist/main.js` directly
against the local dev backend venv (sim source — no NI-DAQ hardware needed), which is exactly what
CI already has set up after Task 13's steps.

- [ ] **Step 1: Add the dependency and script**

Modify `apps/force-app/desktop/package.json` — add to `"devDependencies"`:

```json
    "@playwright/test": "^1.48.0",
```

Add to `"scripts"`:

```json
    "test:e2e": "playwright test"
```

Then:

```bash
npm install -w force-app-desktop
npx playwright install chromium --with-deps -w force-app-desktop
```

- [ ] **Step 2: Add the test-only main-process hook**

Modify `apps/force-app/desktop/src/main.ts` — add near the bottom, after `export function
getSupervisor(): SidecarSupervisor | null { ... }`:

```ts
// Test-only: lets the Playwright smoke suite (tests/smoke.spec.ts) reach the supervisor through
// app.evaluate(), which has no access to this module's exports otherwise. Inert unless the test
// runner explicitly opts in via the env var.
if (process.env.FORCE_APP_TEST_HOOKS === '1') {
  (global as unknown as { __forceAppTestHooks: unknown }).__forceAppTestHooks = { getSupervisor };
}
```

- [ ] **Step 3: Write the Playwright config**

Create `apps/force-app/desktop/playwright.config.ts`:

```ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'tests',
  timeout: 60_000,
  // Both tests spawn the real backend on a port the supervisor resolves itself; running them
  // concurrently risks two Electron instances racing for the same fallback port.
  workers: 1,
  reporter: 'list',
});
```

- [ ] **Step 4: Write the smoke tests**

Create `apps/force-app/desktop/tests/smoke.spec.ts`:

```ts
import { test, expect, _electron as electron, type ElectronApplication } from '@playwright/test';
import path from 'node:path';

const MAIN_JS = path.join(__dirname, '..', 'dist', 'main.js');

async function launch(): Promise<ElectronApplication> {
  return electron.launch({
    args: [MAIN_JS],
    env: { ...process.env, FORCE_APP_TEST_HOOKS: '1' },
    timeout: 30_000,
  });
}

async function recorderUrl(app: ElectronApplication): Promise<string> {
  return app.evaluate(async ({ app: electronApp }) => {
    const fs = require('node:fs');
    const path = require('node:path');
    const cfgPath = path.join(electronApp.getPath('userData'), 'config.json');
    return JSON.parse(fs.readFileSync(cfgPath, 'utf-8')).recorderUrl as string;
  });
}

test('the bundle boots: sidecar reaches healthy and the renderer loads on app://force', async () => {
  const app = await launch();
  try {
    const window = await app.firstWindow();
    await window.waitForURL((url) => url.href.startsWith('app://force/'), { timeout: 30_000 });

    const url = await recorderUrl(app);
    const health = await fetch(`${url}/health`);
    expect(health.ok).toBe(true);
  } finally {
    await app.close();
  }
});

test('a killed backend is restarted and stays reachable', async () => {
  const app = await launch();
  try {
    const window = await app.firstWindow();
    await window.waitForURL((url) => url.href.startsWith('app://force/'), { timeout: 30_000 });

    const pid = await app.evaluate(() => {
      const hooks = (global as unknown as { __forceAppTestHooks: { getSupervisor: () => { getPid(): number | null } } })
        .__forceAppTestHooks;
      const currentPid = hooks.getSupervisor().getPid();
      if (currentPid) process.kill(currentPid);
      return currentPid;
    });
    expect(pid).toBeGreaterThan(0);

    const url = await recorderUrl(app);
    await expect
      .poll(
        async () => {
          try {
            const res = await fetch(`${url}/health`, { signal: AbortSignal.timeout(1000) });
            return res.ok;
          } catch {
            return false;
          }
        },
        { timeout: 20_000, intervals: [500] },
      )
      .toBe(true);
  } finally {
    await app.close();
  }
});
```

- [ ] **Step 5: Run and verify**

```bash
npm run build:web
npm run build -w force-app-desktop
npm run test:e2e -w force-app-desktop
```

Expected: PASS (2 tests). The second test takes several seconds — it's waiting on the supervisor's
real backoff-and-restart cycle, not hanging.

- [ ] **Step 6: Add the CI step**

Modify `.github/workflows/force-app-release.yml` — add two new steps **after** "Build the
Electron installer" and **before** "Upload installer artifact". They must come after the build
step specifically because `tests/smoke.spec.ts` launches `dist/main.js`, which that step is what
compiles (`npm run build` runs `tsc` before `electron-builder` packages the result) — inserting
these steps any earlier would run Playwright against a `dist/` that doesn't exist yet:

```yaml
      - name: Install Playwright browsers
        working-directory: apps/force-app/desktop
        run: npx playwright install chromium --with-deps

      - name: Run desktop smoke tests
        working-directory: apps/force-app/desktop
        run: npm run test:e2e
```

- [ ] **Step 7: Commit**

```bash
git add apps/force-app/desktop/package.json apps/force-app/desktop/package-lock.json apps/force-app/desktop/playwright.config.ts apps/force-app/desktop/tests apps/force-app/desktop/src/main.ts .github/workflows/force-app-release.yml
git commit -m "test(force-app-desktop): Playwright smoke tests for bundle boot and sidecar recovery"
```

---

## Final verification

Run once, from the repo root, after Task 14:

```bash
npm run typecheck -w force-app-desktop   # clean
npm run typecheck -w force-app-web       # clean
npm run test -w force-app-desktop        # ~22 unit tests passing
npm run test:e2e -w force-app-desktop    # 2 Playwright smoke tests passing
npm run build:web                        # succeeds
npm run package -w force-app-desktop     # produces release/*.exe + latest.yml
```

## Deferred — recorded, not done

- **Deploying Task 12's changes to `d1-server`.** This plan commits the CORS/Caddyfile/
  docker-compose changes and the publish script, but applying them (editing the live `.env`,
  `docker compose up -d`) requires access to that host and is explicitly the user's call per
  Task 12 Step 6 — not something to do unprompted from a workstation session.
- **Pushing a `force-app-v*` tag.** Task 13's workflow is dormant until a tag is pushed; no
  version has been agreed with the user, so this plan does not pick one.
- **Code signing.** Explicitly out of scope for v1 per the design spec — revisit only if signing
  and the update-feed hosting are reconsidered together (see ADR-0010's open decisions).
- **Local-only / no-Directus mode, macOS/Linux builds, offline `/filter` and `/octrees`
  fallbacks.** All explicitly out of scope for v1.
- **Schema-contract mechanism after the eventual repo split** (ADR-0010 step 2, not attempted by
  this plan) remains an open decision, unrelated to packaging.
