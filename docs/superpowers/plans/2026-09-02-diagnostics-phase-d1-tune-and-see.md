# Diagnostics Phase D-1 — Tune-and-See Implementation Plan

> Executed inline via superpowers:executing-plans. Checkbox steps track progress.

**Goal:** Make the Diagnostics Workbench a working tune-and-see surface: every D1AN channel
selectable, clusters visible as an overlay with a per-cluster summary, and a recipe panel that
previews parameter changes against `diag-service` in ~200 ms and triggers a full bake when
you're satisfied.

**Architecture:** The diag analysis cloud is 18k–~1M points (256/rev), so the Spatial panel
renders it as a flat `THREE.Points` scatter — no potree-core, instant recolour, and preview is
just a WorkingSet swap. The recipe is a client-side object initialised from the row's
`diag_recipe` (or the built-in default); editing a param debounce-fires `POST /diag/preview`,
whose D1AN bytes replace the WorkingSet. Bake stays the existing `diag_status='pending'` PATCH
flow. The full-resolution octree view is Phase D-2, not this plan.

**Spec:** `docs/superpowers/specs/2026-09-01-diagnostics-recipe-workbench-design.md` (Components 5–6)

## Global Constraints

- `scripts/diag/` is not touched by this phase. The client never computes a statistic — it
  renders columns the server produced and thresholds/highlights them.
- The recipe's canonical hash lives in Python (`diag.recipe.recipe_hash`). The client compares
  the *bake's* stored `diag_recipe_hash` against a client-computed hash only for the "bake
  stale" indicator; a mismatch is advisory, never blocking.
- `packages/force-plotting` is consumed from source by two hosts. New `ForceHost` fields must be
  added to the interface and BOTH wrappers (`StandaloneDiagnosticsWorkbench.vue`,
  `DirectusForceDashboard.vue` if it renders the workbench — check; currently only the
  standalone one does) plus `apps/force-app/web/src/config.ts` and `.env.*`.
- Tests: `npm test -w @d1/force-plotting`; typecheck: `npm run typecheck -w @d1/force-plotting`
  and `-w force-app-web`. Both must pass before each commit.

## File Structure

| File | Responsibility |
|---|---|
| `packages/force-plotting/src/selection.ts` | **Modify.** WorkingSet carries all 11 D1AN columns; `Selection` attribute kind generalised to any channel; add `clusterStats()`. |
| `packages/force-plotting/src/recipeChannels.ts` | **Create.** `STEP_META` (op → label, tier, produced columns, param schema); `DEFAULT_RECIPE`; `recipeChannels(recipe)`; `recipeHashLike(recipe)`. |
| `packages/force-plotting/src/diagPreview.ts` | **Create.** `fetchDiagPreview(analysisId, recipe, fromStep, signal)` → `DiagAttrs`. |
| `packages/force-plotting/src/host.ts` | **Modify.** Add `readonly diagUrl: string` to `ForceHost`. |
| `packages/force-plotting/src/DiagScatter.vue` | **Create.** Flat `THREE.Points` render: continuous channels (viridis) + categorical `cluster_id` (palette, noise dimmed), selection-dim in the shader, top-down ortho. |
| `packages/force-plotting/src/ClusterTable.vue` | **Create.** Per-cluster summary; row click emits a cluster selection. |
| `packages/force-plotting/src/RecipePanel.vue` | **Create.** Step list with `on` toggles + param inputs; emits `preview` (debounced) and `bake`. |
| `packages/force-plotting/src/DiagnosticsWorkbench.vue` | **Modify.** Add the recipe column; Spatial → `DiagScatter`; channel selector from `recipeChannels`; cluster overlay + table; state strip. |
| `packages/force-plotting/src/index.ts` | **Modify.** Export the new modules. |
| `apps/force-app/web/src/force/StandaloneDiagnosticsWorkbench.vue` | **Modify.** Supply `diagUrl`; pass `analysisId`; handle `bake`. |
| `apps/force-app/web/src/force/DiagnosticsPage.vue` | **Modify.** Pass `analysis-id` through; the Bake handler is its existing `build()`. |
| `apps/force-app/web/src/config.ts` | **Modify.** `diagUrl` default `/diag`. |
| `apps/force-app/web/.env.development` / `.env.local` / `.env.example` / `.env.production` | **Modify.** `VITE_DIAG_URL`. |

---

## Task 1: WorkingSet carries every channel; cluster stats

**Files:** modify `packages/force-plotting/src/selection.ts`, `selection.test.ts`.

- [ ] **Step 1** — extend `WorkingSet` with `giStar, giSig, clusterId, glosh, envBand: Float32Array`. Extend `REQUIRED_COLUMNS` to the full D1AN set (`gi_star, gi_sig, cluster_id, glosh, env_band`). Map them in `workingSetFromD1an`. Keep the "missing column" throw.
- [ ] **Step 2** — generalise `Selection` `'attribute'` kind: `column: ChannelKey` where `ChannelKey = 'tsaResid'|'residZ'|'giStar'|'giSig'|'clusterId'|'glosh'|'envBand'`. Update `matches()` with a `CHANNEL_ACCESSOR: Record<ChannelKey, (ws, i) => number>` map. Add a `'cluster'` kind: `{ kind: 'cluster'; id: number }` matching `ws.clusterId[i] === id` — the natural output of a ClusterTable row click.
- [ ] **Step 3** — add `export function clusterStats(ws: WorkingSet): ClusterRow[]` returning, per distinct `clusterId` (including `-1` = noise): `{ id, n, fraction, meanAbsResidZ, maxGiStar, rMin, rMax }`, sorted by `n` descending with noise last.
- [ ] **Step 4** — tests: a WorkingSet from a synthetic `DiagAttrs` with two clusters + noise; assert `clusterStats` counts, fractions sum to 1, noise sorts last; assert `matches` for `attribute` on `giStar` and for `cluster`. Run `npm test -w @d1/force-plotting`.
- [ ] **Step 5** — commit `feat(diag-ui): WorkingSet carries every D1AN channel + clusterStats`.

---

## Task 2: `diagUrl` host field + the preview client

**Files:** modify `host.ts`, `index.ts`, `StandaloneDiagnosticsWorkbench.vue`, `config.ts`, `.env.*`; create `diagPreview.ts`.

- [ ] **Step 1** — `ForceHost`: add `readonly diagUrl: string` with a doc comment mirroring `filterUrl`. `resetForceHost` / tests unaffected. Update `host.test.ts`'s fixture host if it constructs a full `ForceHost` literal.
- [ ] **Step 2** — `config.ts`: add `diagUrl` to `AppConfig`, `KEYS`, `defaults` (`import.meta.env.VITE_DIAG_URL ?? '/diag'`). `.env.development` + `.env.example`: `VITE_DIAG_URL=/diag`. `.env.local`: `VITE_DIAG_URL=http://localhost/diag` (matches its `VITE_OCTREE_URL` origin). `.env.production`: `VITE_DIAG_URL=/diag`.
- [ ] **Step 3** — `StandaloneDiagnosticsWorkbench.vue`: add `get diagUrl() { return getConfig().diagUrl; }` to the `setForceHost` call.
- [ ] **Step 4** — `diagPreview.ts`:

```ts
import { parseD1an, type DiagAttrs } from './diagAttrs';
import { useForceHost } from './host';
import type { Recipe } from './recipeChannels';

export async function fetchDiagPreview(
	analysisId: string, recipe: Recipe, fromStep: number | null, signal?: AbortSignal,
): Promise<DiagAttrs> {
	const host = useForceHost();
	const res = await fetch(`${host.diagUrl}/preview`, {
		method: 'POST', signal, credentials: host.fetchCredentials,
		headers: { 'Content-Type': 'application/json', ...host.authHeaders() },
		body: JSON.stringify({ analysis_id: analysisId, recipe, from_step: fromStep, layers: null }),
	});
	if (!res.ok) throw new Error(`diag preview: ${res.status} ${(await res.text()).slice(0, 200)}`);
	return parseD1an(await res.arrayBuffer());
}
```

- [ ] **Step 5** — export `fetchDiagPreview` from `index.ts` (recipe types too, after Task 3). Typecheck both packages. Commit `feat(diag-ui): diagUrl host field + preview client`.

---

## Task 3: The recipe model for the client

**Files:** create `recipeChannels.ts`, `recipeChannels.test.ts`.

- [ ] **Step 1** — `Recipe` / `RecipeStep` types matching the Python JSON shape (`recipe_version`, `name`, `steps: [{id, op, on, params}]`).
- [ ] **Step 2** — `DEFAULT_RECIPE`: transcribe `scripts/diag/recipe.py`'s `DEFAULT_RECIPE` verbatim (7 steps, ids s1..s7, envelope `on:false`). A `recipeChannels.test.ts` case asserts the op list + ids + envelope-off so drift from Python is caught.
- [ ] **Step 3** — `STEP_META: Record<string, { label; tier: 'base'|'derived'; produces: string[]; params: ParamSpec[] }>` for the 7 ops. `ParamSpec = { key; label; kind: 'number'|'select'; min?; max?; step?; options? }`. Only the tunable params (frame_transform.channel, angular_resample.samples_per_rev, radial_detrend.n_bins/min_per_bin, getis_ord.k/alpha, hdbscan.grid_target/min_cluster_size, envelope.bandwidth_frac/fn_hz). `tsa` has none.
- [ ] **Step 4** — `recipeChannels(recipe): { key: ChannelKey; label: string; produced: boolean }[]` — the full channel list, each flagged whether an *enabled* step in `recipe` produces it (walk enabled steps, union `STEP_META[op].produces`, map snake→camel). This is what populates the Spatial channel selector "built from recipe.produces".
- [ ] **Step 5** — `recipeHashLike(recipe): string` — a stable JSON hash of `enabled steps' {op, sorted params}` (mirror `_canonical` + sha256-hex-16 via `crypto.subtle` — async; or a synchronous FNV-1a is fine since it's advisory only). Document it is advisory, only for the "bake stale" chip.
- [ ] **Step 6** — tests + typecheck. Commit `feat(diag-ui): client recipe model + channel derivation`.

---

## Task 4: `DiagScatter.vue` — the flat point render

**Files:** create `DiagScatter.vue`.

- [ ] **Step 1** — props: `workingSet: WorkingSet | null`, `channel: ChannelKey`, `colormap: string`, `pointSize: number`, `selection: Selection`, `clusterMode: boolean`. Emits `climits` (auto colour range for the continuous legend).
- [ ] **Step 2** — Three setup mirroring `DiagOctreeView.vue`'s camera/controls block (top-down `OrthographicCamera`, `OrbitControls` with rotation locked, render-on-demand `invalidate()`), but the geometry is a single `THREE.BufferGeometry` with `position` (x, y, 0 from the WorkingSet) and per-vertex `aValue` (the selected channel) + `aSelected` (0/1 from `matches()` — computed in JS on selection change, cheap at ≤1M).
- [ ] **Step 3** — ShaderMaterial:
  - continuous: `vColor = texture(uGradient, clamp((aValue - uRange.x)/(uRange.y - uRange.x)))`.
  - `clusterMode`: `aValue` carries `cluster_id`; `id < 0` → dim grey `(0.30)`; else `uPalette[int(mod(id, 12))]` (a 12-entry categorical palette uniform).
  - `aSelected < 0.5 && uSelActive` → multiply rgb by 0.15 (dim non-selected).
  - `gl_PointSize = uSize` (screen-space, no distance attenuation for ortho).
- [ ] **Step 4** — watchers: `workingSet` change → rebuild geometry + recompute range; `channel` change → repack `aValue` + range (no geometry rebuild); `selection` change → repack `aSelected`. All call `invalidate()`.
- [ ] **Step 5** — auto colour range: `channel` continuous → 1st/99th percentile of `aValue` (reuse the approach from `liveCloud.ts axisAutoLimits` if it fits, else inline). Emit `climits`.
- [ ] **Step 6** — typecheck. Manual check deferred to Task 6's browser run. Commit `feat(diag-ui): DiagScatter flat point render with cluster overlay`.

---

## Task 5: `ClusterTable.vue` + `RecipePanel.vue`

**Files:** create `ClusterTable.vue`, `RecipePanel.vue`.

- [ ] **Step 1** — `ClusterTable.vue`: props `{ rows: ClusterRow[]; activeId: number | null }`. A compact table (id chip coloured to match the DiagScatter palette, n, % of cut, mean |resid_z|, max gi\*, r-range). Row click → `emit('select', id)`; clicking the active row again → `emit('select', null)`. Noise row styled muted.
- [ ] **Step 2** — `RecipePanel.vue`: props `{ recipe: Recipe; baked: boolean; bakeStale: boolean; previewing: boolean; previewMs: number | null; previewError: string | null }`. `v-model:recipe` (emit `update:recipe` on any edit). Renders each step: drag handle is out of scope (no reorder in D-1), an `on` checkbox, the step label + tier badge, and `STEP_META[op].params` as `<input type=number>` / `<select>`. A footer: **Preview** state line (`previewing… / previewed in {ms} ms (approximate) / {error}`) and a **Bake** button that `emit('bake')`, disabled while `previewing`.
- [ ] **Step 3** — the panel does NOT call the service itself; `DiagnosticsWorkbench` owns the debounced `fetchDiagPreview` and passes results down. The panel only edits the recipe object and shows status.
- [ ] **Step 4** — typecheck. Commit `feat(diag-ui): ClusterTable + RecipePanel`.

---

## Task 6: Rewire `DiagnosticsWorkbench.vue` + host wrappers + verify

**Files:** modify `DiagnosticsWorkbench.vue`, `index.ts`, `StandaloneDiagnosticsWorkbench.vue`, `DiagnosticsPage.vue`.

- [ ] **Step 1** — `DiagnosticsWorkbench.vue` props gain `analysisId: string` and `bakedRecipeHash: string | null` (from the row). Add `recipe = ref(structuredClone(props.initialRecipe ?? DEFAULT_RECIPE))`.
- [ ] **Step 2** — layout: three grid columns — `recipe` (w:3), `spatial` (w:6), `signal` (w:3). Recipe column renders `<RecipePanel v-model:recipe="recipe" ... @bake="$emit('bake', recipe)" />`.
- [ ] **Step 3** — `workingSet`: `bakedWS` from `attrs.d1an` on mount (as today). `previewWS` from `fetchDiagPreview`, debounced 400 ms, `AbortController` cancelling in-flight, fired by a deep `watch(recipe)`. `activeWS = computed(() => previewWS.value ?? bakedWS.value)`. Everything downstream (DiagScatter, ClusterTable, SelectionInspector, chart) reads `activeWS`.
- [ ] **Step 4** — Spatial panel → `<DiagScatter :working-set="activeWS" :channel="channel" :cluster-mode="channel === 'clusterId'" :selection="selection" />`. Channel `<select>` options come from `recipeChannels(recipe)` — disabled `<option>` for channels no enabled step produces.
- [ ] **Step 5** — below the scatter (panel footer or a stacked mini-panel): cluster overlay toggle + `<ClusterTable :rows="clusterStats(activeWS)" :active-id="selection?.kind === 'cluster' ? selection.id : null" @select="onClusterSelect" />`.
- [ ] **Step 6** — state strip (replaces / augments `BandwidthStrip` row): `previewing` → "previewing recipe · {ms} ms · approximate — Bake for exact"; else if `bakeStale` (`recipeHashLike(recipe) !== bakedRecipeHash`) → "showing last bake · recipe edited since"; else "baked".
- [ ] **Step 7** — `index.ts`: export `DiagScatter`, `ClusterTable`, `RecipePanel`, `DEFAULT_RECIPE`, `recipeChannels`, `fetchDiagPreview`, and the `Recipe`/`ChannelKey`/`ClusterRow` types.
- [ ] **Step 8** — `StandaloneDiagnosticsWorkbench.vue`: pass `:analysis-id`, `:initial-recipe`, `:baked-recipe-hash`; handle `@bake` by calling up to `DiagnosticsPage`. `DiagnosticsPage.vue`: thread `analysis_id` (it's the row `id`), `diag_recipe`, `diag_recipe_hash` into `DIAG_FIELDS` and the props; `@bake` → its existing `build()` but PATCH `diag_recipe` = the edited recipe alongside `diag_status='pending'`.
- [ ] **Step 9** — `npm test -w @d1/force-plotting`, `npm run typecheck -w @d1/force-plotting`, `npm run typecheck -w force-app-web`. All green.
- [ ] **Step 10** — browser verification via the running dev server + Chrome:
  - `npm run dev -w force-app-web`, open `/diagnostics`, log in (user does the password), select `10-AA-MF-2023-03-31-F19-30MPM_0.05feed_0.1DoC` (204,800 pts — the stress case).
  - Confirm: scatter renders; channel selector lists all channels; switching to `gi_sig` shows the significant hotspots; `cluster_id` shows the cluster overlay; the cluster table populates; editing `getis_ord.k` fires a preview that visibly changes `gi_star`/`gi_sig` within ~1 s and the strip says "approximate"; Bake sets the row pending.
  - Screenshot the workbench with the cluster overlay + table visible.
- [ ] **Step 11** — commit `feat(diag-ui): tune-and-see workbench — channels, clusters, live recipe preview`.

---

## Self-Review

**Spec coverage (Components 5–6):** channel selector from `recipe.produces` (Task 3 `recipeChannels` + Task 6 Step 4); cluster overlay (Task 4 categorical mode + Task 6 Step 4); per-cluster table (Task 5 + Task 1 `clusterStats`); recipe panel with step params + Bake (Task 5); "clicking a step previews" is approximated as "editing a param previews" — per-step `from_step` view is deferred with the true prefix cache; the honest state strip (Task 6 Step 6).

**Deliberate scope cuts vs the spec's Component 6 diagram:** no step reorder / add-step / remove-step in D-1 (toggles + param edits only — reorder needs `validate_recipe` client-side, deferred to Phase F's recipe library work); paint tools are Phase E; the C/D tabbed Orders/Envelope panels are not built here (the existing `BandwidthStrip` stays); `grid-layout-plus` dockable panels kept but not made poppable. The "v1: tune-and-see" outcome — hotspots and clusters visible and adjustable — is fully delivered.

**Deviation from the spec's rendering approach:** flat `THREE.Points` instead of potree-core for the analysis cloud, justified by the measured point counts (≤204,800 across all baked cuts; ≤~1M worst case). `DiagOctreeView.vue` is retained unused for Phase D-2's full-resolution view. Recorded in `DiagScatter.vue`'s header.

**Type consistency:** `ChannelKey` is defined once in `selection.ts` and imported everywhere. `Recipe`/`RecipeStep` in `recipeChannels.ts`. `ClusterRow` in `selection.ts` (it is a stats shape, co-located with `clusterStats`). `fetchDiagPreview` returns `DiagAttrs` (from `diagAttrs.ts`) which `workingSetFromD1an` already consumes.
