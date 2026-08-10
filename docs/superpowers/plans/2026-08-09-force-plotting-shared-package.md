# Force Plotting Shared Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two forked copies of the force plotting code with one shared `packages/force-plotting` workspace consumed by both the Directus module and the standalone app.

**Architecture:** An npm workspace package holds a single copy of the ten shared files. The three places the two environments genuinely differ (service URLs + auth style, record navigation, asset download) are abstracted behind a `ForceHost` object supplied by each consumer. The host is a module-level singleton rather than Vue `provide`/`inject`, because two of the consumers of it (`filterChain.ts`, `liveCache.ts`) are plain TypeScript modules with no component instance.

**Tech Stack:** Vue 3 SFCs, TypeScript, Vite (standalone app), `@directus/extensions-sdk` rollup builder (Directus module), Vitest, npm workspaces.

## Global Constraints

- **The standalone copy is canonical for every file.** It is strictly newer. The Directus copy is missing four bug fixes and one function — do not merge "both directions" and do not preserve Directus-side behaviour that differs.
- `core/extensions` is **bind-mounted live into the running Directus container** (`…\D1-Database\core\extensions -> /directus/extensions`). Directus serves `dist/index.js`, not `src/`. Editing source is safe; rebuilding `dist/index.js` is the production cutover. Never build to `dist/` before Task 10.
- Node v24.11.1, npm 11.6.2. Shared dependency versions across both consumers are already identical: `three@^0.160.0`, `grid-layout-plus@^1.1.1`, `potree-core@^2.0.4`.
- Package name: `@d1/force-plotting`. Extension package name: `directus-extension-d1-force-dashboard`. Web app package name: `force-app-web`.
- The package is **source-only** — consumers bundle it from `src/`. No build step, no `dist/`, no publishing (publishing arrives with the repo split, ADR-0010 step 2).
- Tab indentation, matching the existing files.

### Implicit package contract (do not "fix" these)

The shared components rely on three globals supplied by the embedding app, not by imports. Both consumers already satisfy them; preserve that.

- **`v-icon` and `v-progress-circular`** must be registered globally. Directus provides them natively; the standalone app registers shims in `apps/force-app/web/src/main.ts` (`app.component('v-icon', VIcon)` etc.).
- **`<private-view>`** wraps the dashboard template (line 1269–1734). It is a real Directus admin component; in the standalone app it is *not* registered or styled, so Vue renders it as an unknown element and its children render through it as a transparent wrapper (with a dev-mode resolution warning). This is identical in both current copies. A verbatim move preserves the behaviour in both — do not remove it or convert it to a `<div>` as part of this work.

## Divergence Reference

Measured with `diff` on 2026-08-09. Total 138 changed lines across 10 files.

| File | Δ lines | Nature |
|---|---|---|
| `ForceChart.vue` | 0 | identical |
| `SpectrumView.vue` | 0 | identical |
| `frmExport.ts` | 0 | identical |
| `signalStats.ts` | 0 | identical |
| `FrmOctree.vue` | 5 | environment: octree base URL |
| `FrmCloud.vue` | 18 | **standalone-only fix**: `renderer.clear()` white-flash fixes |
| `liveCloud.ts` | 19 | **standalone-only fix**: empty-array guards, NaN clamp |
| `filterChain.ts` | 21 | environment: filter base URL, Bearer vs cookie auth |
| `liveCache.ts` | 30 | **standalone-only feature**: `buildSeriesEnvelope()` |
| `ForceDashboard.vue` | 45 | environment (record nav, asset download, density) + **standalone-only fix** (ops list self-filter on deep link) |

`LocalCaptureView.vue` lives in the same directory but has **no** Directus counterpart. It is standalone-only and does not move into the package.

## File Structure

**Create:**
- `package.json` (repo root) — npm workspace declaration. Does not exist today.
- `packages/force-plotting/package.json` — `@d1/force-plotting`, deps + vitest.
- `packages/force-plotting/tsconfig.json` — typecheck config.
- `packages/force-plotting/src/host.ts` — `ForceHost` interface, `setForceHost`, `useForceHost`.
- `packages/force-plotting/src/host.test.ts` — host singleton tests.
- `packages/force-plotting/src/index.ts` — public exports.
- `packages/force-plotting/src/{ForceChart,SpectrumView,FrmCloud,FrmOctree,ForceDashboard}.vue`
- `packages/force-plotting/src/{frmExport,signalStats,liveCache,liveCloud,filterChain}.ts`
- `packages/force-plotting/src/{liveCache,liveCloud}.test.ts`
- `apps/force-app/web/src/force/StandaloneForceDashboard.vue` — host wiring + `<ForceDashboard />`.
- `core/extensions/d1-force-dashboard/src/DirectusForceDashboard.vue` — host wiring + `<ForceDashboard />`.

**Modify:**
- `apps/force-app/web/package.json` — add `@d1/force-plotting` dependency.
- `apps/force-app/web/src/router.ts` — point the force route at `StandaloneForceDashboard.vue`.
- `apps/force-app/web/src/force/LocalCaptureView.vue` — import shared components from the package.
- `core/extensions/d1-force-dashboard/package.json` — add `@d1/force-plotting` dependency.
- `core/extensions/d1-force-dashboard/src/index.ts` — route to `DirectusForceDashboard.vue`.
- `.gitignore` — ignore root `node_modules/` and `apps/force-app/web/.vite/`.

**Delete (Tasks 8–9, after each consumer is switched):**
- `apps/force-app/web/src/force/{ForceChart,SpectrumView,FrmCloud,FrmOctree,ForceDashboard}.vue`
- `apps/force-app/web/src/force/{frmExport,signalStats,liveCache,liveCloud,filterChain}.ts`
- `apps/force-app/web/src/force/{liveCache,liveCloud}.test.ts`
- `core/extensions/d1-force-dashboard/src/*` except `index.ts` and the new wrapper.

---

### Task 1: Root npm workspace

Establishes dependency resolution for `packages/force-plotting`. A spike on 2026-08-09 confirmed the Directus builder **can** compile a `.vue` file from outside the extension directory, but bare imports like `three` fail to resolve — "treating it as an external dependency" — because no `node_modules` exists at or above `packages/`. A workspace root fixes this by hoisting.

**Files:**
- Create: `package.json` (repo root)
- Modify: `.gitignore`
- Delete: `apps/force-app/web/package-lock.json`, `core/extensions/d1-force-dashboard/package-lock.json`

**Interfaces:**
- Consumes: nothing.
- Produces: a root `node_modules/` with hoisted shared dependencies; `npm run -w <name>` available for both consumers.

- [ ] **Step 1: Commit first so the lockfiles are recoverable**

`npm install` rewrites `node_modules` for both consumers and replaces two lockfiles with one. Committing first makes `git checkout -- .` a complete rollback.

```bash
git status --short   # expect a clean tree apart from apps/force-app/web/.vite/
```

- [ ] **Step 2: Record the baseline build outputs**

Both consumers must still build identically after the workspace change. Capture the current state to compare against.

```bash
cd apps/force-app/web && npm run build && ls -l dist/assets | head -5
cd ../../../core/extensions/d1-force-dashboard && ls -l dist/index.js
```

Expected: the web build succeeds. Note the extension's `dist/index.js` size (1021923 bytes, dated Aug 4) — **do not rebuild it.**

- [ ] **Step 3: Create the root package.json**

```json
{
  "name": "d1-database",
  "private": true,
  "version": "0.0.0",
  "description": "D1 LIMS monorepo. Workspaces cover the JS/TS surfaces only; Python services and Directus SQL migrations are managed separately.",
  "workspaces": [
    "packages/*",
    "apps/force-app/web",
    "core/extensions/d1-force-dashboard"
  ],
  "scripts": {
    "test": "npm run test --workspaces --if-present",
    "typecheck": "npm run typecheck --workspaces --if-present",
    "build:web": "npm run build -w force-app-web",
    "build:extension": "npm run build -w directus-extension-d1-force-dashboard"
  }
}
```

- [ ] **Step 4: Add ignores**

Append to `.gitignore`:

```gitignore
# npm workspace root
/node_modules/
# Vite dev cache
apps/force-app/web/.vite/
```

- [ ] **Step 5: Remove the per-package lockfiles and install**

Workspaces require a single root lockfile; leaving the nested ones causes npm to resolve inconsistently.

The two workspaces' existing `node_modules/` must go too. npm treats a pre-existing nested install as already valid, so leaving them in place makes `npm install` exit 0 **without hoisting anything** — the exact silent failure this task exists to prevent.

```bash
rm apps/force-app/web/package-lock.json core/extensions/d1-force-dashboard/package-lock.json
rm -rf apps/force-app/web/node_modules core/extensions/d1-force-dashboard/node_modules
npm install
```

Expected: creates root `node_modules/` and `package-lock.json`, plus symlinks for each workspace. No `ERESOLVE` errors — the three shared dependency versions are already identical across both consumers.

Verify hoisting actually happened rather than trusting the exit code:

```bash
ls -d node_modules/three node_modules/potree-core node_modules/grid-layout-plus
ls -d apps/force-app/web/node_modules/three 2>/dev/null && echo "NOT HOISTED — investigate"
```

Expected: the three resolve at the root; the second command prints nothing.

- [ ] **Step 6: Verify both consumers still build**

```bash
npm run build:web
(cd core/extensions/d1-force-dashboard && npx directus-extension build -t module -i src/index.ts -o /tmp/ext-check.js)
```

Expected: both succeed. The `-o` redirect is mandatory — a bare extension build would overwrite the live `dist/index.js`.

Note the extension build is invoked directly rather than as `npm run build:extension -- -o …`. Arguments after `--` are swallowed by the nested `npm run -w` inside that script and never reach `directus-extension`, which then fails on the leftover path. It fails safely — it errors before writing anything — but it does not perform the check.

- [ ] **Step 7: Commit**

```bash
git add package.json package-lock.json .gitignore
git add -u apps/force-app/web/package-lock.json core/extensions/d1-force-dashboard/package-lock.json
git commit -m "build: add npm workspace root for shared force-plotting package"
```

---

### Task 2: The ForceHost seam

**Files:**
- Create: `packages/force-plotting/package.json`, `packages/force-plotting/tsconfig.json`
- Create: `packages/force-plotting/src/host.ts`
- Test: `packages/force-plotting/src/host.test.ts`

**Interfaces:**
- Consumes: Task 1's workspace root.
- Produces: `ForceHost` interface; `setForceHost(host: ForceHost): void`; `useForceHost(): ForceHost` (throws if unset); `resetForceHost(): void` (tests only).

- [ ] **Step 1: Create the package manifest**

```json
{
  "name": "@d1/force-plotting",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "description": "Shared force-analysis plotting components. Consumed from source by the Directus module and the standalone force app; no build step.",
  "main": "src/index.ts",
  "exports": { ".": "./src/index.ts" },
  "scripts": {
    "test": "vitest run",
    "typecheck": "vue-tsc --noEmit"
  },
  "dependencies": {
    "axios": "^1.7.9",
    "grid-layout-plus": "^1.1.1",
    "potree-core": "^2.0.4",
    "three": "^0.160.0",
    "vue": "^3.5.13",
    "vue-router": "^4.5.0"
  },
  "devDependencies": {
    "@types/three": "^0.160.0",
    "typescript": "^5.7.3",
    "vitest": "^4.1.10",
    "vue-tsc": "^2.2.0"
  }
}
```

- [ ] **Step 2: Create the package tsconfig**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "module": "ESNext",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "preserve",
    "strict": true,
    "noUnusedLocals": false,
    "noUnusedParameters": false,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src/**/*.ts", "src/**/*.vue"]
}
```

- [ ] **Step 3: Write the failing test**

Create `packages/force-plotting/src/host.test.ts`:

```ts
import { describe, expect, it, beforeEach } from 'vitest';
import { setForceHost, useForceHost, resetForceHost, type ForceHost } from './host';

const stub: ForceHost = {
	api: {} as ForceHost['api'],
	currentUser: () => ({ admin_access: true }),
	filterUrl: '/filter',
	octreeUrl: '/octrees',
	authHeaders: () => ({}),
	fetchCredentials: 'include',
	openRecord: () => {},
	downloadAsset: async () => {},
	dense: false,
};

describe('force host', () => {
	beforeEach(() => resetForceHost());

	it('throws a diagnostic error when no host has been installed', () => {
		expect(() => useForceHost()).toThrow(/setForceHost/);
	});

	it('returns the installed host', () => {
		setForceHost(stub);
		expect(useForceHost().filterUrl).toBe('/filter');
	});

	it('reads through getters so runtime config changes are picked up', () => {
		let url = '/filter';
		setForceHost({ ...stub, get filterUrl() { return url; } });
		url = 'https://elsewhere.example/filter';
		expect(useForceHost().filterUrl).toBe('https://elsewhere.example/filter');
	});
});
```

- [ ] **Step 4: Run the test to verify it fails**

```bash
npm run test -w @d1/force-plotting
```

Expected: FAIL — `Cannot find module './host'`.

- [ ] **Step 5: Implement host.ts**

```ts
import type { AxiosInstance } from 'axios';

/**
 * The subset of the Directus user record the dashboard uses for ownership scoping.
 * `role` may be a bare id string or a hydrated object depending on how far the
 * Directus user store has loaded, so both shapes are permitted.
 */
export interface ForceHostUser {
	role?: string | { id?: string; admin_access?: boolean };
	admin_access?: boolean;
	[key: string]: unknown;
}

/**
 * Everything the shared plotting code needs from its embedding environment.
 *
 * Two environments implement this: the Directus admin module (same-origin,
 * cookie-authenticated, in-app router) and the standalone force app
 * (cross-origin, Bearer-authenticated, separate tab). These were previously two
 * forked copies of the whole dashboard; this interface is the entire real
 * difference between them.
 *
 * `filterUrl` and `octreeUrl` are declared readonly rather than as methods so
 * implementations can supply them as getters — the standalone app's service URLs
 * are reconfigurable at runtime via Settings > General, so a value captured once
 * at setup would go stale.
 */
export interface ForceHost {
	/** Authenticated axios instance: Directus's `useApi()` or the standalone Bearer client. */
	api: AxiosInstance;
	/** Current user, for admin-role/ownership scoping. Called during computed evaluation so reactivity tracks. */
	currentUser(): ForceHostUser | null;
	/** Base URL for the filter sidecar (/run, /fft, /spectrogram). No trailing slash. */
	readonly filterUrl: string;
	/** Base URL for the octree static server. No trailing slash. */
	readonly octreeUrl: string;
	/** Extra headers for raw `fetch` calls. Bearer token standalone; empty in Directus (cookie). */
	authHeaders(): Record<string, string>;
	/** Credentials mode for raw `fetch` calls. 'include' in Directus (session cookie); 'omit' standalone. */
	fetchCredentials: RequestCredentials;
	/** Open a Directus record editor for the given collection and primary key. */
	openRecord(collection: string, id: string): void;
	/** Download a Directus file by id, handling whichever auth style applies. */
	downloadAsset(fileId: string): Promise<void>;
	/** Tighter padding for the standalone app, which has no Directus chrome competing for space. */
	dense: boolean;
}

// A module-level singleton rather than Vue provide/inject: filterChain.ts is a
// plain module with no component instance, so inject() is unavailable there.
let current: ForceHost | null = null;

export function setForceHost(host: ForceHost): void {
	current = host;
}

export function useForceHost(): ForceHost {
	if (!current) {
		throw new Error(
			'@d1/force-plotting: no host installed. Call setForceHost() in the consuming ' +
			'component before rendering ForceDashboard.',
		);
	}
	return current;
}

/** Test-only: clear the installed host so cases start from a known state. */
export function resetForceHost(): void {
	current = null;
}
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
npm run test -w @d1/force-plotting
```

Expected: PASS, 3 tests.

- [ ] **Step 7: Commit**

```bash
git add packages/force-plotting
git commit -m "feat(force-plotting): add ForceHost seam for environment differences"
```

---

### Task 3: Move the four identical files

Zero-risk: these are byte-identical between the two copies, so there is no merge decision to make.

**Files:**
- Create: `packages/force-plotting/src/ForceChart.vue`, `SpectrumView.vue`, `frmExport.ts`, `signalStats.ts`
- Create: `packages/force-plotting/src/index.ts`

**Interfaces:**
- Consumes: Task 2's package skeleton.
- Produces: `ForceChart`, `SpectrumView` components; whatever `frmExport.ts` and `signalStats.ts` already export (`computeSignalStats`, `type SignalStats`, and the export helpers).

- [ ] **Step 1: Confirm they are still identical before copying**

```bash
for f in ForceChart.vue SpectrumView.vue frmExport.ts signalStats.ts; do
  diff -q "core/extensions/d1-force-dashboard/src/$f" "apps/force-app/web/src/force/$f" && echo "$f identical"
done
```

Expected: all four report identical. If any differs, stop — the divergence reference is stale and needs re-measuring.

- [ ] **Step 2: Copy them into the package**

```bash
for f in ForceChart.vue SpectrumView.vue frmExport.ts signalStats.ts; do
  cp "apps/force-app/web/src/force/$f" "packages/force-plotting/src/$f"
done
```

- [ ] **Step 3: Create the public entry point**

Create `packages/force-plotting/src/index.ts`. Later tasks extend it; this is the initial version.

```ts
export { setForceHost, useForceHost, resetForceHost } from './host';
export type { ForceHost, ForceHostUser } from './host';

export { default as ForceChart } from './ForceChart.vue';
export { default as SpectrumView } from './SpectrumView.vue';

export { computeSignalStats } from './signalStats';
export type { SignalStats } from './signalStats';
export * from './frmExport';
```

- [ ] **Step 4: Typecheck**

```bash
npm run typecheck -w @d1/force-plotting
```

Expected: **exactly these three errors and no others** — the four identical files import siblings that do not move until Tasks 4 and 5. This is the expected intermediate state, not a defect:

```
src/frmExport.ts(6,27): error TS2307: Cannot find module './liveCloud'
src/signalStats.ts(9,28): error TS2307: Cannot find module './liveCache'
src/SpectrumView.vue(7,52): error TS2307: Cannot find module './filterChain'
```

Any *additional* error is a real problem — investigate before continuing. The package first typechecks clean at the end of Task 5, once `filterChain.ts` lands.

- [ ] **Step 5: Commit**

```bash
git add packages/force-plotting/src
git commit -m "feat(force-plotting): move the four byte-identical shared files"
```

---

### Task 4: Move the three files with standalone-only fixes

These have **no** environment differences — the entire diff is fixes the Directus copy never received. Copy the standalone version verbatim; no host wiring needed.

**Files:**
- Create: `packages/force-plotting/src/liveCache.ts`, `liveCloud.ts`, `FrmCloud.vue`
- Test: `packages/force-plotting/src/liveCache.test.ts`, `liveCloud.test.ts`
- Modify: `packages/force-plotting/src/index.ts`

**Interfaces:**
- Consumes: Task 3's `index.ts`.
- Produces: `FrmCloud` component; `cacheGet`, `cachePut`, `decimateCache`, `parseCache`, `buildSeriesEnvelope`, `type Cache`, `type EnvSeries` from `liveCache`; `type SpeedMode` and the cloud builders from `liveCloud`.

- [ ] **Step 1: Copy the standalone versions and their tests**

```bash
for f in liveCache.ts liveCloud.ts FrmCloud.vue liveCache.test.ts liveCloud.test.ts; do
  cp "apps/force-app/web/src/force/$f" "packages/force-plotting/src/$f"
done
```

- [ ] **Step 2: Confirm the standalone-only fixes came across**

These four greps guard against copying the stale Directus version by mistake. Each must produce output.

```bash
grep -n "buildSeriesEnvelope" packages/force-plotting/src/liveCache.ts
grep -n "Number.isNaN(v)" packages/force-plotting/src/liveCloud.ts
grep -n "if (t.length === 0) return -1" packages/force-plotting/src/liveCloud.ts
grep -n "renderer.clear()" packages/force-plotting/src/FrmCloud.vue
```

Expected: `buildSeriesEnvelope` at ~line 57; the NaN clamp in `clamp01`; the empty-array guard in the binary search; two `renderer.clear()` call sites in `FrmCloud.vue`.

- [ ] **Step 3: Point FrmCloud at the host for its api instance**

`FrmCloud.vue` is the one file here that imports `@directus/extensions-sdk` (for `useApi()`). Replace that import:

```ts
// remove:
import { useApi } from '@directus/extensions-sdk';
// add:
import { useForceHost } from './host';
```

and replace the `useApi()` call:

```ts
// remove:
const api = useApi();
// add:
const api = useForceHost().api;
```

- [ ] **Step 4: Extend index.ts**

Append to `packages/force-plotting/src/index.ts`:

```ts
export { default as FrmCloud } from './FrmCloud.vue';
export { buildSeriesEnvelope, cacheGet, cachePut, decimateCache, parseCache } from './liveCache';
export type { Cache, EnvSeries } from './liveCache';
export type { SpeedMode } from './liveCloud';
```

- [ ] **Step 5: Run tests and typecheck**

```bash
npm run test -w @d1/force-plotting
npm run typecheck -w @d1/force-plotting
```

Expected: the moved `liveCache` and `liveCloud` tests pass alongside the 3 host tests.

Typecheck is expected to report **exactly one remaining error** — `SpectrumView.vue` importing `./filterChain`, which lands in Task 5. The two errors Task 3 saw (`frmExport.ts` → `./liveCloud`, `signalStats.ts` → `./liveCache`) must now be gone; if either persists, the corresponding file did not land correctly.

- [ ] **Step 6: Commit**

```bash
git add packages/force-plotting/src
git commit -m "feat(force-plotting): move liveCache, liveCloud and FrmCloud (standalone versions)"
```

---

### Task 5: Move filterChain.ts onto the host seam

**Files:**
- Create: `packages/force-plotting/src/filterChain.ts`
- Test: `packages/force-plotting/src/filterChain.test.ts`
- Modify: `packages/force-plotting/src/index.ts`

**Interfaces:**
- Consumes: `useForceHost` from Task 2.
- Produces: `fetchFiltered`, `fetchFilteredFft`, `chainActive`, `chainSummary`, `defaultChain`, `type FilterChain`.

- [ ] **Step 1: Copy the standalone version**

```bash
cp apps/force-app/web/src/force/filterChain.ts packages/force-plotting/src/filterChain.ts
```

- [ ] **Step 2: Write the failing test**

Create `packages/force-plotting/src/filterChain.test.ts`. This pins both host wirings — the bug it prevents is a consumer silently losing its auth style.

```ts
import { describe, expect, it, beforeEach, vi, afterEach } from 'vitest';
import { setForceHost, resetForceHost, type ForceHost } from './host';
import { defaultChain, fetchFiltered } from './filterChain';

function hostWith(over: Partial<ForceHost>): ForceHost {
	return {
		api: {} as ForceHost['api'],
		currentUser: () => null,
		filterUrl: '/filter',
		octreeUrl: '/octrees',
		authHeaders: () => ({}),
		fetchCredentials: 'include',
		openRecord: () => {},
		downloadAsset: async () => {},
		dense: false,
		...over,
	};
}

describe('filterChain host wiring', () => {
	beforeEach(() => {
		resetForceHost();
		vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })));
	});
	afterEach(() => vi.unstubAllGlobals());

	it('calls the host filter URL with Bearer headers and no cookies (standalone)', async () => {
		setForceHost(hostWith({
			filterUrl: 'https://d1.example/filter',
			authHeaders: () => ({ Authorization: 'Bearer t0ken' }),
			fetchCredentials: 'omit',
		}));
		// fetchFiltered pipes the response through parseCache, which rejects on this stub
		// body. Irrelevant here — the assertions are about how fetch was called, not the
		// parsed result — so swallow it rather than constructing a valid binary cache.
		await fetchFiltered('op-1', defaultChain()).catch(() => {});
		const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
		expect(url).toBe('https://d1.example/filter/run');
		expect((init.headers as Record<string, string>).Authorization).toBe('Bearer t0ken');
		expect(init.credentials).toBe('omit');
	});

	it('calls the same-origin filter URL with cookies and no Authorization (Directus)', async () => {
		setForceHost(hostWith({ filterUrl: '/filter', authHeaders: () => ({}), fetchCredentials: 'include' }));
		// fetchFiltered pipes the response through parseCache, which rejects on this stub
		// body. Irrelevant here — the assertions are about how fetch was called, not the
		// parsed result — so swallow it rather than constructing a valid binary cache.
		await fetchFiltered('op-1', defaultChain()).catch(() => {});
		const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
		expect(url).toBe('/filter/run');
		expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
		expect(init.credentials).toBe('include');
	});
});
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
npm run test -w @d1/force-plotting -- filterChain
```

Expected: FAIL — the copied file still imports `../config` and `../directusClient`, which do not exist in the package.

- [ ] **Step 4: Rewire to the host**

Replace the two standalone imports:

```ts
// remove:
import { getConfig } from '../config';
import { authHeaders } from '../directusClient';
// add:
import { useForceHost } from './host';
```

Then in each of the three fetch call sites (`/run`, `/fft`, `/spectrogram`), replace the URL and headers and add the credentials mode. For `/run`:

```ts
const host = useForceHost();
const res = await fetch(`${host.filterUrl}/run`, {
	method: 'POST',
	credentials: host.fetchCredentials,
	headers: { 'Content-Type': 'application/json', ...host.authHeaders() },
	body: JSON.stringify(payload),
});
```

Apply the identical pattern to `/fft` and `/spectrogram`, preserving each call's existing `body`. Update the comment above the group to describe both environments:

```ts
// ---- filter-service calls. Same-origin via Caddy /filter/* under Directus (session cookie
// flows automatically); cross-origin with a Bearer token in the standalone app, which the
// service forwards to Directus when fetching the cache. The host supplies both. ----
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
npm run test -w @d1/force-plotting
npm run typecheck -w @d1/force-plotting
```

Expected: tests PASS, all suites. **This is the first task where typecheck must be completely clean** — `filterChain.ts` was the last unresolved sibling import. Any remaining `TS2307 Cannot find module` error means an earlier file did not land.

- [ ] **Step 6: Extend index.ts and commit**

Append:

```ts
export { chainActive, chainSummary, defaultChain, fetchFiltered, fetchFilteredFft } from './filterChain';
export type { FilterChain } from './filterChain';
```

```bash
git add packages/force-plotting/src
git commit -m "feat(force-plotting): move filterChain onto the host seam"
```

---

### Task 6: Move FrmOctree.vue onto the host seam

**Files:**
- Create: `packages/force-plotting/src/FrmOctree.vue`
- Modify: `packages/force-plotting/src/index.ts`

**Interfaces:**
- Consumes: `useForceHost`.
- Produces: `FrmOctree` component.

- [ ] **Step 1: Copy the standalone version**

```bash
cp apps/force-app/web/src/force/FrmOctree.vue packages/force-plotting/src/FrmOctree.vue
```

- [ ] **Step 2: Rewire the octree base URL**

Replace the import:

```ts
// remove:
import { getConfig } from '../config';
// add:
import { useForceHost } from './host';
```

Replace the base URL construction (around line 179):

```ts
// The octree host is configured, not assumed to be the SPA origin: the standalone app is
// served from a different origin than the octree server, while the Directus module is
// same-origin. The host supplies whichever applies.
const base = `${useForceHost().octreeUrl}/${props.octreePath}/`;
```

- [ ] **Step 3: Typecheck**

```bash
npm run typecheck -w @d1/force-plotting
```

Expected: no errors.

- [ ] **Step 4: Extend index.ts and commit**

Append:

```ts
export { default as FrmOctree } from './FrmOctree.vue';
```

```bash
git add packages/force-plotting/src
git commit -m "feat(force-plotting): move FrmOctree onto the host seam"
```

---

### Task 7: Move ForceDashboard.vue onto the host seam

The largest file (2060 lines) and the one carrying all three remaining environment concerns.

**Files:**
- Create: `packages/force-plotting/src/ForceDashboard.vue`
- Modify: `packages/force-plotting/src/index.ts`

**Interfaces:**
- Consumes: `useForceHost`, plus the sibling components moved in Tasks 3–6.
- Produces: `ForceDashboard` component, taking no props — all environment coupling arrives via the host.

- [ ] **Step 1: Copy the standalone version**

```bash
cp apps/force-app/web/src/force/ForceDashboard.vue packages/force-plotting/src/ForceDashboard.vue
```

- [ ] **Step 2: Confirm the standalone-only fix came across**

```bash
grep -n "filterSampleId.value = selectedSampleId.value" packages/force-plotting/src/ForceDashboard.vue
grep -n "scrollIntoView" packages/force-plotting/src/ForceDashboard.vue
```

Expected: both present (~line 934). If absent, the Directus copy was copied by mistake — redo Step 1.

- [ ] **Step 3: Replace the environment imports**

```ts
// remove:
import { useApi, useStores } from '@directus/extensions-sdk';
import { getConfig } from '../config';
// add:
import { useForceHost } from './host';
```

`useRoute` / `useRouter` from `vue-router` stay — both environments provide a router, and the dashboard's own deep-link handling (`?operation=`) is identical in each.

- [ ] **Step 4: Replace the api and user-store wiring**

```ts
// remove:
const api = useApi();
const { useUserStore } = useStores();
const userStore = useUserStore();
// add:
const host = useForceHost();
const api = host.api;
```

Then in `isAdminRole`, read through the host. Reactivity still tracks because the property access happens during the computed's evaluation:

```ts
const isAdminRole = computed(() => {
	const cu = host.currentUser() as any;
	const roleId = typeof cu?.role === 'string' ? cu.role : cu?.role?.id;
	return ADMIN_ROLE_IDS.has(roleId) || cu?.role?.admin_access === true || cu?.admin_access === true;
});
```

Search for any other `userStore.currentUser` references and replace each with `host.currentUser()`.

- [ ] **Step 5: Replace record navigation and asset download**

```ts
function openSampleForm() { if (sampleInfo.value?.id) host.openRecord('physical_samples', String(sampleInfo.value.id)); }
function openOpForm() { if (op.value?.operation_id) host.openRecord('manufacturing_operations', String(op.value.operation_id)); }

function downloadFile(fileId: string) { void host.downloadAsset(fileId); }
```

This removes the standalone copy's inline blob-download implementation and the Directus copy's inline `<a href>` implementation — both now live in their respective host adapters (Tasks 8 and 9).

- [ ] **Step 6: Make layout density host-driven**

The dashboard's root element is `<div class="fd">` at line 1270, immediately inside `<private-view title="Force Analysis">`. Add the class binding there:

```html
<div class="fd" :class="{ dense: host.dense }" @click="rightAddOpen = false">
```

In `<style>`, keep the roomier Directus values as the base and add dense overrides. The copied file currently holds the *dense* values, so each base rule below is a revert to the Directus figure with a `.dense` override restoring the standalone one. The four rules, at their current line numbers:

```css
/* line 1806 */
.panel-ops .list { max-height: 38vh; }
.dense .panel-ops .list { max-height: none; }

/* line 1851 — keep the existing background/border/border-radius declarations */
.card { padding: 16px 18px; }
.dense .card { padding: 12px 14px; }

/* line 1855 — keep the existing display/font/letter-spacing/colour declarations */
.info-head { margin-bottom: 11px; }
.dense .info-head { margin-bottom: 8px; }

/* line 1868 */
.kv { display: grid; grid-template-columns: auto 1fr; gap: 7px 12px; font-size: 12.5px; margin-bottom: 4px; }
.dense .kv { gap: 4px 10px; font-size: 12px; margin-bottom: 2px; }
```

Note `.panel-ops .list` is declared twice (lines 1773 and 1806); line 1806 is the later, winning declaration and the one to change. Leave line 1773 alone.

- [ ] **Step 7: Point sibling imports at the package-local copies**

The relative sibling imports (`./ForceChart.vue`, `./SpectrumView.vue`, `./FrmCloud.vue`, `./FrmOctree.vue`, `./liveCloud`, `./liveCache`, `./signalStats`, `./filterChain`) all resolve correctly inside the package already. Confirm none point outside it:

```bash
grep -n "from '\.\./" packages/force-plotting/src/ForceDashboard.vue
```

Expected: no output. Any hit is a leftover standalone-only import that must be moved to the host.

- [ ] **Step 8: Typecheck and test**

```bash
npm run typecheck -w @d1/force-plotting
npm run test -w @d1/force-plotting
```

Expected: no type errors; all tests pass.

- [ ] **Step 9: Extend index.ts and commit**

Append:

```ts
export { default as ForceDashboard } from './ForceDashboard.vue';
```

```bash
git add packages/force-plotting/src
git commit -m "feat(force-plotting): move ForceDashboard onto the host seam"
```

---

### Task 8: Switch the standalone app to the package

**Files:**
- Create: `apps/force-app/web/src/force/StandaloneForceDashboard.vue`
- Modify: `apps/force-app/web/package.json`, `apps/force-app/web/src/router.ts`, `apps/force-app/web/src/force/LocalCaptureView.vue`
- Delete: the ten now-duplicated files under `apps/force-app/web/src/force/`

**Interfaces:**
- Consumes: `@d1/force-plotting` exports from Tasks 3–7.
- Produces: a working standalone app with no local copy of the plotting code.

- [ ] **Step 1: Add the dependency**

In `apps/force-app/web/package.json`, add to `dependencies`:

```json
"@d1/force-plotting": "*"
```

Then:

```bash
npm install
```

- [ ] **Step 2: Create the host adapter component**

Create `apps/force-app/web/src/force/StandaloneForceDashboard.vue`:

```vue
<script setup lang="ts">
// Installs the standalone app's ForceHost, then renders the shared dashboard. The standalone
// app is cross-origin to Directus and Bearer-authenticated, so raw fetches carry an
// Authorization header and must NOT send cookies; assets cannot use a plain <a href> because
// the token would not travel with it.
import { ForceDashboard, setForceHost } from '@d1/force-plotting';
import { api, authHeaders } from '../directusClient';
import { authStore } from '../authStore';
import { getConfig } from '../config';

setForceHost({
	api,
	currentUser: () => authStore.currentUser.value,
	// Getters, not captured values: Settings > General can retarget these at runtime.
	get filterUrl() { return getConfig().filterUrl; },
	get octreeUrl() { return getConfig().octreeUrl; },
	authHeaders,
	fetchCredentials: 'omit',
	// The record editors live in the Directus admin UI, which is a different origin here.
	openRecord: (collection, id) => {
		window.open(`${getConfig().directusUrl}/admin/content/${collection}/${id}`, '_blank', 'noopener');
	},
	// Assets are cross-origin and Bearer-authed, so fetch through the authenticated client
	// and save the blob rather than relying on an anchor href.
	downloadAsset: async (fileId) => {
		try {
			const res = await api.get(`/assets/${fileId}`, { params: { download: '' }, responseType: 'blob' });
			const url = URL.createObjectURL(res.data as Blob);
			const a = document.createElement('a');
			a.href = url; a.download = String(fileId);
			document.body.appendChild(a); a.click(); a.remove();
			setTimeout(() => URL.revokeObjectURL(url), 10_000);
		} catch { /* best-effort */ }
	},
	dense: true,
});
</script>

<template><ForceDashboard /></template>
```

- [ ] **Step 3: Point the router at it**

In `apps/force-app/web/src/router.ts` line 13, swap the lazy import. Leave `path` and `name` unchanged so existing deep links keep working:

```ts
// before:
{ path: 'plot', name: 'plot', component: () => import('./force/ForceDashboard.vue') },
// after:
{ path: 'plot', name: 'plot', component: () => import('./force/StandaloneForceDashboard.vue') },
```

Line 14 (`plot/local/:captureId` → `LocalCaptureView.vue`) is unaffected.

- [ ] **Step 4: Repoint LocalCaptureView.vue**

`LocalCaptureView.vue` stays in the app but imports shared components. Change its relative imports to package imports, for example:

```ts
// before:
import FrmCloud from './FrmCloud.vue';
import { parseCache } from './liveCache';
// after:
import { FrmCloud, parseCache } from '@d1/force-plotting';
```

Apply to every symbol it takes from a moved file. Find them with:

```bash
grep -n "from './" apps/force-app/web/src/force/LocalCaptureView.vue
```

- [ ] **Step 5: Delete the duplicated files**

```bash
cd apps/force-app/web/src/force
rm ForceChart.vue SpectrumView.vue FrmCloud.vue FrmOctree.vue ForceDashboard.vue
rm frmExport.ts signalStats.ts liveCache.ts liveCloud.ts filterChain.ts
rm liveCache.test.ts liveCloud.test.ts
cd -
```

- [ ] **Step 6: Verify no dangling references**

```bash
grep -rn "force/ForceDashboard\|force/FrmCloud\|force/liveCache\|force/filterChain" apps/force-app/web/src || echo "clean"
```

Expected: `clean`.

- [ ] **Step 7: Typecheck, test and build**

```bash
npm run typecheck -w force-app-web
npm run test -w force-app-web
npm run build:web
```

Expected: all pass. The `@directus/extensions-sdk` Vite alias and `src/shims/directus-sdk.ts` are now unused by the plotting code — leave both in place for now; the record/ and settings/ surfaces may still rely on them. Remove only if Step 6's grep plus `grep -rn "extensions-sdk" apps/force-app/web/src` shows no remaining users.

- [ ] **Step 8: Manually verify the app**

```bash
npm run dev -w force-app-web
```

Open `http://localhost:5180`, log in, and check: sample list loads, selecting an operation renders the six charts, the FRM map renders without a white flash, filters apply, a file downloads, and "open record" opens the Directus admin in a new tab.

- [ ] **Step 9: Commit**

```bash
git add -A apps/force-app/web packages/force-plotting package-lock.json
git commit -m "refactor(force-app): consume shared force-plotting package"
```

---

### Task 9: Switch the Directus module to the package

Source-only. The live `dist/index.js` is **not** rebuilt here — that is Task 10.

**Files:**
- Create: `core/extensions/d1-force-dashboard/src/DirectusForceDashboard.vue`
- Modify: `core/extensions/d1-force-dashboard/package.json`, `core/extensions/d1-force-dashboard/src/index.ts`
- Delete: the ten now-duplicated files under `core/extensions/d1-force-dashboard/src/`

**Interfaces:**
- Consumes: `@d1/force-plotting` exports.
- Produces: a module bundle built from shared source, verified at a temp output path.

- [ ] **Step 1: Add the dependency**

In `core/extensions/d1-force-dashboard/package.json`, add to `dependencies`:

```json
"@d1/force-plotting": "*"
```

Then:

```bash
npm install
```

- [ ] **Step 2: Create the host adapter component**

Create `core/extensions/d1-force-dashboard/src/DirectusForceDashboard.vue`:

```vue
<script setup lang="ts">
// Installs the Directus admin's ForceHost, then renders the shared dashboard. Inside Directus
// everything is same-origin and authenticated by the session cookie, so raw fetches send
// credentials and need no Authorization header, and assets download via a plain anchor.
import { useApi, useStores } from '@directus/extensions-sdk';
import { useRouter } from 'vue-router';
import { ForceDashboard, setForceHost } from '@d1/force-plotting';

const api = useApi();
const router = useRouter();
const { useUserStore } = useStores();
const userStore = useUserStore();

setForceHost({
	api,
	currentUser: () => userStore.currentUser,
	filterUrl: '/filter',
	octreeUrl: `${window.location.origin}/octrees`,
	authHeaders: () => ({}),
	fetchCredentials: 'include',
	openRecord: (collection, id) => { router.push(`/content/${collection}/${id}`); },
	downloadAsset: async (fileId) => {
		const a = document.createElement('a');
		a.href = `/assets/${fileId}?download`;
		a.rel = 'noopener';
		document.body.appendChild(a); a.click(); a.remove();
	},
	dense: false,
});
</script>

<template><ForceDashboard /></template>
```

- [ ] **Step 3: Repoint the module registration**

Rewrite `core/extensions/d1-force-dashboard/src/index.ts`:

```ts
import { defineModule } from '@directus/extensions-sdk';
import DirectusForceDashboard from './DirectusForceDashboard.vue';

// Standalone, home-styled force-analysis explorer: sample -> operation -> detail -> graphs
// (6 force/FFT charts + the per-axis FRM fingerprint). Reads the machining_force_analysis rows
// populated by scripts/force_orchestrator.py. The dashboard itself lives in
// packages/force-plotting and is shared with the standalone force app; this module only
// supplies the Directus-flavoured host (see DirectusForceDashboard.vue).
export default defineModule({
	id: 'd1-force-dashboard',
	name: 'Force Analysis',
	icon: 'insights',
	routes: [{ path: '', component: DirectusForceDashboard }],
});
```

- [ ] **Step 4: Delete the duplicated files**

```bash
cd core/extensions/d1-force-dashboard/src
rm ForceChart.vue SpectrumView.vue FrmCloud.vue FrmOctree.vue ForceDashboard.vue
rm frmExport.ts signalStats.ts liveCache.ts liveCloud.ts filterChain.ts
cd -
ls core/extensions/d1-force-dashboard/src
```

Expected: exactly `DirectusForceDashboard.vue` and `index.ts`.

- [ ] **Step 5: Build to a temp path and verify**

```bash
(cd core/extensions/d1-force-dashboard && npx directus-extension build -t module -i src/index.ts -o /tmp/ext-new.js)
ls -l /tmp/ext-new.js
```

(Invoked directly, not via `npm run build:extension -- -o …` — arguments after `--` never reach `directus-extension` through the nested `npm run -w`.)

Expected: "Done" with **no** "could not be resolved – treating it as an external dependency" warnings. Any such warning means a dependency is unresolvable from `packages/force-plotting` and Task 1's hoisting is incomplete — stop and fix before Task 10.

Sanity-check the size against the current live bundle (1021923 bytes). A result within roughly ±20% is expected; an order-of-magnitude difference means dependencies were externalised rather than bundled.

- [ ] **Step 6: Commit**

```bash
git add -A core/extensions/d1-force-dashboard package-lock.json
git commit -m "refactor(force-dashboard): consume shared force-plotting package"
```

---

### Task 10: Production cutover

The only step that changes what Directus serves. Restarting the container is a brief outage — do this deliberately, not at a moment when someone is mid-experiment.

**Files:**
- Modify: `core/extensions/d1-force-dashboard/dist/index.js`

**Interfaces:**
- Consumes: the verified temp build from Task 9.
- Produces: the live Directus module running shared code.

- [ ] **Step 1: Back up the current live bundle**

```bash
cp core/extensions/d1-force-dashboard/dist/index.js \
   "core/extensions/d1-force-dashboard/dist/index.js.bak-$(date +%Y%m%d-%H%M%S)"
ls -l core/extensions/d1-force-dashboard/dist/
```

- [ ] **Step 2: Build to dist**

```bash
npm run build:extension
ls -l core/extensions/d1-force-dashboard/dist/index.js
```

Expected: "Done", no unresolved-dependency warnings, fresh timestamp.

- [ ] **Step 3: Restart Directus to load it — MANDATORY, not optional**

`docker-compose.yml:94` sets `EXTENSIONS_AUTO_RELOAD: "true"`, which looks like it makes
this step unnecessary. **It does not.** Auto-reload depends on filesystem watch events,
which do not propagate across a Windows→Linux Docker bind mount. In practice Directus
kept serving the bundle it had loaded days earlier, and a full browser suite passed
11/11 against the stale code — the rebuild was invisible. Only an A/B on behaviour
unique to the new bundle exposed it. Always restart.

```bash
"/c/Program Files/Docker/Docker/resources/bin/docker.exe" restart d1-database-directus-1
```

Wait for health:

```bash
"/c/Program Files/Docker/Docker/resources/bin/docker.exe" ps --filter name=d1-database-directus-1 --format "{{.Status}}"
```

Expected: `Up … (healthy)`.

- [ ] **Step 4: Verify in the browser**

Open the Directus admin, go to **Force Analysis**, and confirm: the module loads, the sample list populates, selecting an operation renders the charts, the FRM map renders (this is where the previously-missing `liveCloud` NaN fixes should now prevent a white canvas), filters apply, "open record" navigates in-app, and a file download works.

Also confirm the fixes the Directus copy never had: deep-link to an operation via `?operation=<id>` and check the operations list narrows to that sample.

- [ ] **Step 5: Rollback procedure (only if Step 4 fails)**

```bash
cp core/extensions/d1-force-dashboard/dist/index.js.bak-<stamp> \
   core/extensions/d1-force-dashboard/dist/index.js
"/c/Program Files/Docker/Docker/resources/bin/docker.exe" restart d1-database-directus-1
```

Then reopen the module to confirm the previous version is serving again before investigating.

- [ ] **Step 6: Redeploy the `/app/` browser surface**

`docker-compose.yml` bind-mounts `./apps/force-app/web/dist` into Caddy as
`/srv/force-app`, served at `/app/`. Task 8 refactored the app that produces it, so that
surface is stale until rebuilt:

```bash
npm run build:web
```

No restart needed here — Caddy's `file_server` reads from disk per request and
`index.html` is served `no-cache`. Verify by loading `http://localhost/app/`, logging in,
and confirming the sample list populates.

- [ ] **Step 7: Remove the backup**

Only once Step 4 has passed:

```bash
rm core/extensions/d1-force-dashboard/dist/index.js.bak-*
```

**Nothing to commit.** `.gitignore:22` excludes `dist/`, so neither the rebuilt extension
bundle nor the web build is tracked — both are build artifacts regenerated on the host.

- [ ] **Step 8: Record completion in the ADR**

Mark step 1 **DONE** in `docs/adr/0010-force-app-extraction-and-electron-packaging.md`, noting the four bug fixes and one function the Directus surface gained in the process, and commit.

---

## Verification Summary

After Task 10, all of the following must hold:

- `npm run test` at the repo root passes across all workspaces.
- `npm run typecheck` at the repo root passes across all workspaces.
- `ls core/extensions/d1-force-dashboard/src` shows exactly two files.
- `ls apps/force-app/web/src/force` shows exactly `LocalCaptureView.vue` and `StandaloneForceDashboard.vue`.
- No file exists in two places: `diff -r packages/force-plotting/src apps/force-app/web/src/force` reports only the expected extras.
- Both surfaces render the FRM map without a white flash — the fix the Directus copy was missing.
