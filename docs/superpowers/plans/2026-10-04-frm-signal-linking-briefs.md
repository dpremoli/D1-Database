# FRM ↔ Signals linking — worker briefs

Self-contained briefs for streams B, C, D (parallel, after A is merged) and E. Each worker gets
the **Common preamble** plus its own section. Plan: `2026-10-04-frm-signal-linking.md` (same folder).

## Common preamble

You are an implementation worker for the D1-Database force-plotting package. Work only in your own
git worktree, on the files listed as yours. Match surrounding code style (tabs, comment density —
this codebase explains *why* in comments — naming). Commit after each logical step. Never push,
merge, rebase, or touch files outside your ownership list. Moderate pace: focused, no gold-plating.

First: `git merge --ff-only ccr-37b6f575-4lu7ni` in your worktree (your worktree may have been
cut from `main`; the coordinator branch carries the plan and the merged Stream A foundation). If
that fails, `git reset --hard ccr-37b6f575-4lu7ni` (your worktree has no work yet). Then read
`docs/superpowers/plans/2026-10-04-frm-signal-linking.md` (sections "Key design facts", "Shared
contract" and your stream), `.claude/skills/force-app-conventions/SKILL.md`, and
`packages/force-plotting/src/cloudPick.ts` (Stream A's contract implementation — use it, don't
re-implement it).

Node modules resolve from `/home/user/D1-Database/node_modules` via parent directories; if not,
`npm ci --no-audit --no-fund` in your worktree root.

Before your final commit both must pass: `npm test -w @d1/force-plotting` and
`npm run typecheck -w @d1/force-plotting`. Logic you can extract into a pure `.ts` helper should
be extracted and unit-tested (vitest, colocated `*.test.ts`); components aren't mounted in tests.

Commits: Conventional Commits, scope `force-plotting`, ending with exactly:
```
Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WcXKoSEkcV3VPjR2tsnatc
```
Report: worktree path + branch, commit hashes, test/typecheck tails, deviations from the contract,
and anything uncertain or left undone.

## Stream B — Lite cloud (`packages/force-plotting/src/FrmCloud.vue` only)

Add, per the shared contract: emit `pointmenu(PointMenuEvent)`, props `markTime?: number | null`
and `hoverTime?: number | null`, and `revealTime(t: number)` added to `defineExpose`.

1. **Right button must not pan in 2D.** `onDown` currently starts a pan for any button. For a mouse
   `ev.button === 2`, record the down position (for the drag guard) and return without panning
   or capturing. In 3D OrbitControls pans on right-drag; leave that alone, just record the down
   position.
2. **`@contextmenu` on the canvas:** `preventDefault()`. If the right button moved > 4 px since its
   pointerdown, return (it was a pan). If no cache, return. Candidates:
   - GPU path (`usesGpuPath`): `buildPath(cache, effPath, {cropStartSec, cropEndSec, stride})` →
     `pos`/`idx`/`count` (same call `refineGpuPointCount` makes; world mm, z=0, object matrix identity).
   - CPU path, ungridded: `cloud.pos` / `cloud.idx` / `cloud.count` (Stream A added `Cloud.idx`),
     projected through `pointsObj.matrixWorld` (covers the 3D Z scale on `scale.z`).
   - Gridded and 2D: an ungridded `buildPath(...)` as for GPU (pick = nearest sample to the spot).
     Gridded and 3D: emit `{clientX, clientY, point: null, reason: 'gridded'}`.
   - Project with a reused `THREE.Vector3`: `v.set(x,y,z).applyMatrix4(m).project(camera)`; off-clip
     (|ndc|>1) → null; to CSS px `((ndc.x+1)/2*cssW, (1-ndc.y)/2*cssH)`.
   - `keep(k)`: mirror the displayed-range hide: when `!colorScale.greyOutOfRange`, skip points whose
     channel value (`cache[effChannel][idx[k]]`) is outside `[dispMin, dispMax]`.
   - `pickNearest(count, project, px, py, max(8, pointSize*2), keep)`; null → emit with `point: null`
     (no reason) so the host can still show non-point items; else emit
     `pointInfo(cache, idx[k], x, y, rho?)` (rho from `path.rho` when built via buildPath).
   Make sure `matrixWorld` is current (`obj.updateMatrixWorld()`) and the camera matches the last draw.
3. **Rings:** two absolutely-positioned HTML overlays (like `.fc-scale`), `pointer-events: none`:
   pinned (`markTime`, solid accent ring ~12 px) and hover (`hoverTime`, hollow, dimmer ~10 px).
   Position from time: `i = idxOfTime(cache.t, time)`; hidden if `time` is outside
   `[cropStartSec, cropEndSec]` or the cache's `t` range.
   - GPU path: `computeSpiralVertexJS(cache.t[i], cache.revs[i], params, cropStart, cropEnd)` (see
     `updateGpuCropUniforms` for how `tCs`/`revsCs` are derived); hidden if `!visible`.
   - CPU path: `k = findNearestPathIndex(cloud.idx, cloud.count, i)` → `cloud.pos[3k..]`
     through `pointsObj.matrixWorld`.
   - Project as above. Recompute ring positions at the end of `draw()` (both 2D and the 3D early
     return) and in a cheap watcher on `markTime`/`hoverTime` that updates only the overlay refs — hover
     changes must NOT trigger a GL render or rebuild. Use CSS vars with fallbacks for colours
     (e.g. `var(--accent, #38bdf8)`); don't touch the canvas background.
4. **`revealTime(t)`:** compute the point's world position as for the ring; if it is not within the
   current 2D view (use `screenToWorld` of the canvas corners or project and test 0..cssW/0..cssH),
   `seedView()` then set `view.cx/cy` to it and `scheduleDraw()` (works with `sharedView` in compare
   mode). In 3D, set `controls.target` and shift the camera by the same delta. Returns `boolean`
   (false when the point is outside the crop / no cache).
5. Keep comments explaining *why* (e.g. why the GPU path rebuilds positions on the CPU for picking).

## Stream C — octree (`packages/force-plotting/src/FrmOctree.vue` only)

Octree points carry no time, but the octree shares Lite's world frame (mm, part axis at 0,0) and
was built with the fixed geometry the live cache header carries. So pick by position against the
live cache's own path: `octreePathParams(cache, innerDiam, ppr)` + `buildPath`.

Add: props `sampleCache?: Cache | null`, `innerDiam?: number`, `ppr?: number`, `markTime?`,
`hoverTime?`; emit `pointmenu(PointMenuEvent)`; `revealTime(t)` in `defineExpose`.

1. Memoise `buildPath(sampleCache, octreePathParams(...).path, ...window)` keyed on
   (cache identity, innerDiam, ppr); invalidate when they change.
2. **`contextmenu` listener** on the canvas (added in `setupGL` beside the pointer listeners and
   removed wherever those are torn down): `preventDefault()`; ignore if the right button moved
   > 4 px since its pointerdown (OrbitControls pans on right-drag in both 2D and 3D — record the
   down position in `onPtrDown` for `button === 2`). No `sampleCache` → emit
   `{clientX, clientY, point: null, reason: 'no-cache'}`.
3. Project each memoised path sample with the octree `camera` (reused `Vector3`, `.project(camera)`).
   Z in 3D must match the shader: `z = (clamp((v - r0)/(r1 - r0), 0, 1) - 0.5) * uZScale` with
   `v = cache[zSeries][idx[k]]`, `[r0, r1] = material.uniforms.uZRange`, `uZScale` from the
   material; z = 0 when flat. The path positions are true world mm (potree-core restores the LAS
   offset), so no pco matrix is applied to them. Pick radius `max(8, pointSize * 2)`. `keep(k)`
   mirrors the displayed-range discard (`!greyOutOfRange` and the axis value outside dispMin/Max).
   Gridded octrees (`fill`) still pick the nearest sample — that's intended.
4. **Rings** (pinned + hover HTML overlays, same look as Stream B: accent solid ~12 px, hollow
   ~10 px, `pointer-events: none`): `i = idxOfTime(cache.t, time)` → `k = findNearestPathIndex` on
   the memoised path → project. Hidden outside the path's time range or off-screen. The render loop
   runs every frame (see `loop` in `setupGL`), so update ring positions there only when something
   changed (camera matrix/zoom/target or the times) — cheap compare, no allocation per frame.
5. **`revealTime(t)`**: if the sample is off-screen, move `controls.target` (and the camera by the
   same delta) to it, `invalidate()`. Returns boolean.
6. Comment the octree-by-position rationale briefly, pointing at `cloudPick.ts`'s header.

## Stream D — charts (`packages/force-plotting/src/ForceChart.vue`, plus a pure helper if useful)

Add props `markX?: number | null`, `markLabel?: string`; emit
`chartmenu: { clientX: number; clientY: number; x: number }`.

1. **Marker**: when `markX` is within the visible x-range (`geom.x0..x1`), draw a solid vertical
   line across the plot (accent colour via a CSS class using `var(--accent, #f59e0b)`-style var with
   fallback; distinct from the dashed hover line and the teal/red crop handles) and a small tag at
   the top: `markLabel ?? \`t = ${niceNum(markX)} ${xUnit}\``. Render next to the `hoverPt` group
   (around the template's hover `<g>`), `pointer-events: none`.
2. **Right-click**: `@contextmenu` on the chart svg, only for `kind === 'env'` (otherwise let the
   browser menu through): `preventDefault()`, find the nearest bucket with the same
   `hoverIndexAt(g.xs, g.x0, g.x1, frac, g.iA, g.iB)` maths `onHover` uses, and emit
   `{clientX, clientY, x: g.xs[i]}`. Ignore if no data.
3. Make sure a right-button pointerdown doesn't start the rect-zoom drag or a crop-handle drag
   (check `ev.button`).
4. If you extract a helper (e.g. a "marker in view" or label formatter), unit-test it.

## Stream E — dashboard wiring + docs (after A–D are merged)

Files you own: `packages/force-plotting/src/ForceDashboard.vue`, `docs/wiki/force-app/plot-dashboard.md`,
`docs/wiki/force-app/developer-guide.md`, `.claude/skills/force-app-conventions/references/architecture.md`,
`docs/superpowers/specs/2026-10-04-frm-signal-linking-design.md` (new), `docs/superpowers/README.md`,
`apps/force-app/web/src/changelog.ts`. Do not edit FrmCloud/FrmOctree/ForceChart/cloudPick/ContextMenu —
if you find a bug there, report it instead.

What the merged streams give you (read their code):
- `FrmCloud` and `FrmOctree`: emit `pointmenu(PointMenuEvent)`; props `markTime`, `hoverTime`; exposed
  `revealTime(t): boolean`. `FrmOctree` also takes `sampleCache`, `innerDiam`, `ppr`.
- `ForceChart`: props `markX`, `markLabel`; emit `chartmenu({clientX, clientY, x})` (env charts only).
- `ContextMenu.vue` (`x`, `y`, `items: {label, hint?, disabled?, run}[]`, emits `close`) and
  `cloudPick.ts` (`recentreWindow`, `formatPointInfo`, types).

### ForceDashboard.vue
1. **State**: `markTime = ref<number | null>(null)`; `menu = ref<{ x: number; y: number; items: ContextMenuItem[] } | null>(null)`;
   `hoverTime = computed(...)`: `hoverIndex` (:83) is a bucket index into the env series — map it through
   `detail.value?.series?.[<first open axis or 'Fz'>]?.t[hoverIndex]`, only when `chartMode === 'force'`, else null.
   Clear `markTime` and `menu` when `selectedRowId` changes. A window `keydown` Escape clears `markTime`
   when no menu is open and focus isn't in an input/textarea/select/contenteditable (remove the listener on unmount).
2. **Map wiring**: on every Lite `FrmCloud` mount (compare raw + filtered panes, filtered-solo, live — around
   :2670-2690) add `:mark-time="markTime" :hover-time="hoverTime" @pointmenu="openPointMenu"`. On `FrmOctree`
   (:2663) add the same plus `:sample-cache="octreeSampleCache" :inner-diam="Number(detail.inner_diameter) || 0"
   :ppr="Number(detail.pulses_per_rev) || 1"` — the analysis row's stored values, which are what the host
   built the octree with (NOT the editable `editInnerDiam`/`editPpr`).
   `octreeSampleCache = computed(() => { void cacheEpoch.value; const id = detail.value?.live_cache_file; if (!id || !octreeOn.value) return null; const c = cacheGet(id); if (!c) fetchRadialCache(); return c ?? null; })`
   — reuse the existing lazy loader `fetchRadialCache()` / `cacheEpoch` (≈:1890), which the measured-mode radial axis
   already uses, so in practice the cache is usually already in the LRU. Declare it where the TDZ comments allow
   (read the comments around `cacheEpoch` ≈:701 and `liveOn` ≈:500).
3. **Chart wiring**: on the `ForceChart` loop (≈:2512) add `:mark-x="c.kind === 'env' && chartMode === 'force' ? markTime : null"`
   and `@chartmenu="openChartMenu"`.
4. **Render** `<ContextMenu v-if="menu" :x="menu.x" :y="menu.y" :items="menu.items" @close="menu = null" />` once,
   at the dashboard root (it is position:fixed).
5. **Map menu** (`openPointMenu(e: PointMenuEvent)`), items in this order:
   - **Show position in time** — disabled unless `e.point`; hint by reason: `gridded` → "Gridded 3D view averages
     samples", `no-cache` → "Needs this cut's live cache", no point → "No point under the cursor". Run:
     `if (chartMode.value !== 'force') chartMode.value = 'force'` (the existing watch resets zoom), set `markTime = t`,
     then `await nextTick()` and apply `recentreWindow(zoomStart.value, zoomEnd.value, t, tMin, tMax)` via
     `onChartZoom` when non-null, where tMin/tMax are the first/last of the env series `t`.
   - **Clear marker** — only when `markTime != null`.
   - **Copy point info** — disabled unless `e.point`; `navigator.clipboard?.writeText(formatPointInfo(p))`; on
     rejection/absence show the failure through the dashboard's existing transient message mechanism (find the one
     used for save/bake feedback); never throw.
   - **Set crop start here** / **Set crop end here** — disabled unless `e.point`, and when the new edge would cross
     the other (`t >= cropEndSec` / `t <= cropStartSec`, hint "Would cross the crop end/start"). Run
     `onCropEdit('start' | 'end', t)` (:466) — the existing path, so it's batched into Save changes.
6. **Chart menu** (`openChartMenu({clientX, clientY, x: t})`):
   - **Show position on map** — work out the target map: Full/Gridded when `octreeOn`, else Lite when
     `liveAvailable` (if the FRM view is the static Figure, run `chooseMode('lite')` first), else disabled with hint
     "No interactive map for this cut". Disabled with "Outside the cropped window" when Lite and `t` is outside
     `[cropStartSec, cropEndSec]`; with "Needs this cut's live cache" when Full and no `live_cache_file`. Run: set
     `markTime = t`, then on `nextTick` call `(octreeOn ? frmOctreeRef : frmCloudRef).value?.revealTime?.(t)`; if that
     returns false because the view is still loading, keep `pendingReveal = t` and retry it from `onCloudLoaded`
     (and once the octree sample cache arrives), then clear it.
   - **Clear marker** (when set), **Set crop start here**, **Set crop end here** — as in the map menu.
7. Invariants: no new panel type, `RIGHT_KEY` unchanged, `markTime` not persisted (force-app-conventions #11);
   plotting code stays host-agnostic (#10).

### Docs
- `docs/wiki/force-app/plot-dashboard.md`: new section **Linking the map and the signals** (after *FRM map panel*):
  right-click a map point (menu items and what each does), the pinned marker and zoom recentring, chart hover →
  hollow ring on the map, chart right-click → Show position on map, works in Lite and Full/Gridded (Full needs the
  cut's live cache; gridded picks the nearest sample to the spot; gridded 3D Lite can't), Escape / switching
  operation clears the marker. Add one-line cross-links from *Signals panel* and *FRM map panel*. Leave image
  references `../images/force-app/plot-point-menu.png` and `plot-chart-menu.png` commented out
  (`<!-- ![…](…) -->`) — the coordinator adds the screenshots after verification. Follow the page's existing voice.
- `docs/wiki/force-app/developer-guide.md`: one short paragraph (or a bullet under *Things worth knowing*): time is
  the key between chart buckets and cache indices; octree picks work by position through the live cache; pointer to
  `cloudPick.ts` and the spec.
- `.claude/skills/force-app-conventions/references/architecture.md`: add `ContextMenu` and modules `cloudPick`,
  `octreePick`, `chartMark` to the `packages/force-plotting/` row.
- `docs/superpowers/specs/2026-10-04-frm-signal-linking-design.md`: short design spec in the folder's style
  (look at an existing spec's opening): **Status** line (Implemented — on branch, pending merge), problem, decision
  (time as the shared key; GPU/CPU picking; octree picking by position with the frame argument —
  `process_force.m:168-176,227` vs `path.ts` measured branch, LAS offset restored by potree-core; fixed octree
  geometry = cache header + analysis row `pulses_per_rev`/`inner_diameter`), scope, deferred (Record page, reverse
  ring for compare-on-octree…), and the side finding: `saveCropAsOfficial` re-queues octrees but the orchestrator
  ignores the crop override. Add a row to `docs/superpowers/README.md`'s table.
- `apps/force-app/web/src/changelog.ts`: the top entry (0.1.34) is unreleased (no tag) — append one plain-language
  note to its `notes`: Plot page: right-click a point on the FRM map to show when it happened on the force charts
  (and set the crop there); hovering or right-clicking the charts shows the spot on the map, in Lite and Full views.

### Checks
`npm test -w @d1/force-plotting`, `npm run typecheck -w @d1/force-plotting`, `npm test -w force-app-web`,
`npm run typecheck -w force-app-web`, `npm run lint:theme -w force-app-web`, and `npm run build:extension`
(from the repo root; if the extension build needs deps it can't get, report it). For web typecheck in a worktree the
`@d1/force-plotting` symlink in the root node_modules may point at the coordinator checkout — if so run
`npm ci --no-audit --no-fund` in your worktree first.
