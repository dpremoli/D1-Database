# FRM ↔ Signals linking — implementation plan

**Branch:** `ccr-37b6f575-4lu7ni` · **Spec:** `docs/superpowers/specs/2026-10-04-frm-signal-linking-design.md` (written in stream E)

## Status

| Stream | Worktree / agent | Branch | State |
|---|---|---|---|
| A — foundation (cloudPick, ContextMenu, Cloud.idx) | `.claude/worktrees/agent-a5863abf6683d5394` | `worktree-agent-a5863abf6683d5394` (from main b7bdac7) | reviewed, merged |
| B — Lite cloud (FrmCloud.vue) | `.claude/worktrees/agent-a99c2d5ee82294d19` | `worktree-agent-a99c2d5ee82294d19` | reviewed, merged |
| C — octree (FrmOctree.vue) | `.claude/worktrees/agent-a35ad8aa3b3a5f987` | `worktree-agent-a35ad8aa3b3a5f987` | reviewed, merged |
| D — charts (ForceChart.vue) | `.claude/worktrees/agent-a6a66bb9a4070ea27` | `worktree-agent-a6a66bb9a4070ea27` | reviewed, merged |
| E — dashboard wiring + docs | `.claude/worktrees/agent-aec03ca06d8f2455a` | `worktree-agent-aec03ca06d8f2455a` | reviewed, merged |
| Simplify / review / verify | coordinator | `ccr-37b6f575-4lu7ni` | simplify done (A–D); review next |
| PR + merge | coordinator | — | not started |

## Worker agent definition (local-only — recreate at `.claude/agents/force-plotting-implementer.md` if the container was reclaimed)

```markdown
---
name: force-plotting-implementer
description: Implements one stream of a docs/superpowers/plans/ plan in packages/force-plotting (and its Plot-dashboard docs) inside its own git worktree. Commits early, never pushes, merges or rebases.
model: sonnet
effort: medium
skills:
  - force-app-conventions
---
You are an implementation worker for the D1-Database force-plotting package. You work only in
your own git worktree, on the files your brief says you own. Read the brief's plan section and
the shared contract carefully, and match the surrounding code's style (tabs, comment density,
naming). Commit after each logical step with a Conventional Commit message and the trailer lines
your brief gives. Never push, merge, rebase or touch files outside your ownership list. Run the
tests and typecheck your brief names before your final commit, and report: what you changed, the
commits (hashes), test/typecheck output, and anything left undone or uncertain.
```


## Context

The Plot dashboard shows a cut two ways: the **Signals** charts (force against time) and the
**FRM map** (the same samples laid out on the tool path). The only link between them today is
that chart crop edits re-crop the Lite cloud. The user wants to demonstrate the sample ↔ point
correspondence in both directions:

- **Map → time:** right-click a point on the FRM map to get a context menu. **Show position in
  time** pins a marker at that sample's time on the Signals charts.
- **Time → map (the reverse link):** hovering a chart shows a ring at that sample on the map.
  Right-clicking a chart gives **Show position on map**, which pins the ring and the marker.

Decisions:
- **Where:** the Plot dashboard (`ForceDashboard`). That covers the Force App's Plot page and
  Directus *Force Analysis*. It works in **Lite** and in **Full/Gridded** (octree) mode; **Figure**
  is a static PNG. The Record page is deferred.
- **Marker:** pinned and labelled on every Signals chart until cleared. The chart zoom recentres
  on it, keeping its width, if the marker is off-screen. A ring goes on the picked point.
- **Map menu:** Show position in time, Clear marker, Copy point info, Set crop start here,
  Set crop end here.
- **Chart menu:** Show position on map, Clear marker, Set crop start here, Set crop end here.

## Key design facts (from exploration)

- **Time is the shared key.** The charts plot envelope buckets: `hoverIndex` (`ForceDashboard.vue:83`)
  is a bucket index into `detail.series[a].t`. The cloud uses cache indices, from `path.ts`
  `PathResult.idx`. `idxOfTime()` (`liveCache.ts:23`) converts between them. Decimated caches
  (compare, filtered) keep the true `t`.
- **Lite has two render paths** (`FrmCloud.vue`):
  - **GPU** (flat turning spiral): position is computed in the shader. The CPU recovers it with
    `buildPath()` (as `refineGpuPointCount` at :502 already does) or, per sample,
    `frmCloudShader.ts` `computeSpiralVertexJS()`.
  - **CPU** `buildCloud()` (3D, gridded, linear_feed, machine_xyz): has `pos`. It drops
    `path.idx` (`liveCloud.ts:30-38,128`), and one added field keeps it.
- **Why the octree needs a different approach** (*why not on octree*: it can be done):
  - **No time attribute.** Octree points carry only x, y and Fx/Fy/Fz
    (`process_force.m:240`, `force_orchestrator.py:834-849`), so a picked octree point has no time.
  - **Same world frame as Lite.** The octree is in mm, centred on the part axis, with θ=0 at the
    cut start. It uses the same spiral formula as Lite's measured mode (`process_force.m:168-176,227`
    against `path.ts:107-112`), and potree-core restores the LAS offset, so world coordinates are
    true mm.
  - **Fixed geometry.** The octree is built from fixed parameters: measured speed, the auto cut
    start, and the feed and diameter from the `.mat`. These are the same values the live cache
    header carries (`c.csSec`, `c.feed`, `c.diam`).
  - **So picking works by position.** Rebuild the octree's own path from the live cache with
    `buildPath(cache, {turning_spiral, measured, feed: c.feed, diam: c.diam, innerDiam, ppr}, {cropStartSec: c.csSec, cropEndSec: c.ceSec, stride: 1})`.
    Project those samples through the octree's camera and pick the nearest. That gives the
    sample (±1 cache sample when the cache was decimated above 5M samples).
  - **Requirement:** a live cache. Cuts shown with a yellow dot (octree only) get the time items
    disabled, with the hint "needs a live cache".
  - **Gridded octree:** cells aren't samples, so the pick means "nearest sample to this
    location". That's still well defined in 2D.
- `FrmOctree.vue` has an ortho camera with OrbitControls (`:298-302`). Right-drag pans (`:181,301`).
  `currentBounds()` is at `:438`. There are no pointer→world helpers and no picking.
- The only context menu in the repo is `core/extensions/d1-fast-dashboard/src/FastDashboard.vue:307-320,531,660`
  (fixed position, clamped, closes on outside click). `force-plotting` must stay host-agnostic
  (invariant 10), so it gets its own small `ContextMenu.vue`.
- Tests are logic-only (vitest, no component mounting): pure `.ts` modules with colocated
  `*.test.ts`, e.g. `hoverIndex.ts`.
- **Side finding (out of scope, report to user):** `saveCropAsOfficial` (`ForceDashboard.vue:1643-1666`)
  re-queues the octrees, but the orchestrator ignores the crop override, so the rebuilt octree
  still uses the auto crop.

## Shared contract (fixed up front so streams B–D can run in parallel)

Stream A defines it in `packages/force-plotting/src/cloudPick.ts`:

```ts
export interface PointInfo { i: number; t: number; x: number; y: number; rho?: number;
  Fx: number; Fy: number; Fz: number; rpm?: number }
export interface PointMenuEvent { clientX: number; clientY: number;
  point: PointInfo | null; reason?: 'gridded' | 'no-cache' | 'outside-crop' }
export function pickNearest(n: number, project: (k: number) => { px: number; py: number } | null,
  px: number, py: number, radiusPx: number, keep?: (k: number) => boolean): number | null;
export function pointInfo(c: Cache, i: number, x: number, y: number, rho?: number): PointInfo;
export function formatPointInfo(p: PointInfo): string;                       // tab-separated lines
export function recentreWindow(start: number | null, end: number | null, t: number,
  min: number, max: number): { start: number; end: number } | null;         // null = no change
export function findPathIndex(idx: Int32Array, count: number, i: number): number; // binary search, -1 if absent
export function octreePathParams(c: Cache, innerDiam: number, ppr: number): { path: PathParams; window: PathWindow };
```

Component contract:
- **FrmCloud and FrmOctree** both get:
  - emit `pointmenu(PointMenuEvent)`;
  - props `markTime?: number | null` (pinned ring) and `hoverTime?: number | null` (hover ring);
  - exposed `revealTime(t)` (pans the map view so the point at `t` is in view, if it isn't).
- **FrmOctree** also gets props `sampleCache?: Cache | null`, `innerDiam?: number` and
  `ppr?: number`.
- **ForceChart** gets:
  - props `markX?: number | null` and `markLabel?: string`;
  - emit `chartmenu({ clientX, clientY, x })`, where `x` is in x-units (seconds), from the
    nearest bucket under the cursor.

## Implementation streams

| Stream | Files owned | Content |
|---|---|---|
| **A: foundation** (runs first) | `cloudPick.ts` + `cloudPick.test.ts` (new), `liveCloud.ts` (`Cloud.idx`), `ContextMenu.vue` (new), `index.ts` exports | The shared contract above. `ContextMenu` props are `x`, `y` and `items: {label, hint?, disabled?, run}[]`. It's `position: fixed` and clamped like FastDashboard, closes on outside pointerdown, Escape, scroll or blur, uses `role=menu`/`menuitem`, supports arrow keys and focuses the first item. Tests cover the nearest pick, the radius, hidden and off-clip points, recentring (inside, left/right clamp, not zoomed), `findPathIndex`, `pointInfo`, and `octreePathParams` agreeing with `buildPath` measured mode. |
| **B: Lite cloud** | `FrmCloud.vue` | See *Stream B* below. |
| **C: octree** | `FrmOctree.vue` | See *Stream C* below. |
| **D: charts** | `ForceChart.vue` | See *Stream D* below. |
| **E: dashboard + docs** (after B–D) | `ForceDashboard.vue`, docs listed below, `changelog.ts` | See *Stream E* below. |

**Stream B: Lite cloud (`FrmCloud.vue`)**
- **Right-click:**
  - Handle `@contextmenu` and call `preventDefault`. Ignore it if the right button moved more
    than 4 px since pointerdown (3D right-drag pans).
  - Get the candidates:
    - **GPU path:** `buildPath(...)`, giving `pos` and `idx`.
    - **CPU path:** `cloud.pos` and `cloud.idx`.
  - Project with `Vector3.applyMatrix4(obj.matrixWorld).project(camera)`, which covers 2D, 3D
    and the Z scale.
  - `keep()` mirrors the shader's displayed-range hide.
- **Gridded:** pick against an ungridded `buildPath` in 2D. Gridded 3D emits `reason: 'gridded'`.
- **Rings:** HTML overlays (like the scale bar) for `markTime` (solid) and `hoverTime` (hollow).
  - Position, from `idxOfTime`: **GPU path** `computeSpiralVertexJS`; **CPU path**
    `findPathIndex` into `cloud.pos`.
  - Hidden when outside the crop.
  - Hover updates move only the overlay, with no GL redraw.
- **`revealTime`:** sets `view.cx`/`view.cy` to that point (also in compare mode, through
  `sharedView`).

**Stream C: octree (`FrmOctree.vue`)**
- **Right-click:**
  - The same 4 px drag guard.
  - With no `sampleCache`, emit `reason: 'no-cache'`.
  - Otherwise memoise `buildPath(octreePathParams(...))` per cache and params, project its
    samples through the octree camera and `pickNearest`.
  - Z for 3D: use the same series and Z scaling as the octree shader.
- **Rings** and **`revealTime`** work as in stream B: `revealTime` moves `controls.target` and the
  camera.

**Stream D: charts (`ForceChart.vue`)**
- **Marker:** a solid accent line plus a `t = 12.345 s` tag when `markX` is in view. Rendered
  next to `hoverPt` (:474).
- **Right-click:** `@contextmenu` on `env` charts emits `chartmenu` with the time of the nearest
  bucket, using `hoverIndexAt`.

**Stream E: dashboard and docs (`ForceDashboard.vue`, docs, `changelog.ts`)**
- **State:**
  - `markTime` and `menu` (which menu is open, with its items).
  - `hoverTime = computed(series[axis].t[hoverIndex])`.
  - All cleared on an operation switch. Escape clears them too.
- **Wiring:**
  - `@pointmenu` on the Lite cloud, both compare panes and FrmOctree.
  - `:mark-time` and `:hover-time` on each of them.
  - `:sample-cache` on FrmOctree: the live cache, loaded lazily through `cacheGet` and the
    asset API on the first right-click or chart menu in Full mode.
  - `:mark-x` and `@chartmenu` on the `env` charts.
- **Map menu actions:**
  - **Show position in time:** switch to Force mode if needed, set `markTime`, then on
    `nextTick` apply `recentreWindow(...)` through `onChartZoom`.
  - **Copy point info:** `navigator.clipboard` with an inline failure message.
  - **Set crop start / Set crop end:** `onCropEdit('start' | 'end', t)`. That reuses the existing
    path, so the change is batched into **Save changes**. Disabled when the edges would cross.
- **Chart menu action, Show position on map:**
  - If the map is showing a Figure and a live cache exists, switch to Lite first.
  - Then set `markTime` and call `revealTime(t)` on the active map ref.
  - Disabled with a hint when `t` is outside the crop window (Lite) or the octree's cut window.
- No new panel type. No change to `RIGHT_KEY` (invariant 11). `markTime` isn't persisted.
- **Docs:** listed under *Documentation* below.

## Documentation (update the existing docs)

- `docs/wiki/force-app/plot-dashboard.md`:
  - A new **Linking the map and the signals** section: the map menu, the chart menu, the hover
    ring, Full-mode behaviour, the live-cache requirement and gridded behaviour.
  - Cross-links from *Signals panel* and *FRM map panel*.
  - Screenshots `plot-point-menu.png` and `plot-chart-menu.png`, captured during verification.
- `.claude/skills/force-app-conventions/references/architecture.md` (tracked): add `ContextMenu`
  and `cloudPick` to the force-plotting row.
- `docs/wiki/force-app/developer-guide.md`: a note on the force-plotting row that time is the key
  between chart buckets and cache indices, and that octree picking works by position through the
  live cache.
- `docs/superpowers/specs/2026-10-04-frm-signal-linking-design.md`: a short spec (problem, time
  as the key, GPU/CPU/octree picking, the octree frame argument, scope, Record page deferred), plus
  a row in `docs/superpowers/README.md`.
- `apps/force-app/web/src/changelog.ts`: one note. Add it to the top entry only if that entry is
  unreleased (no `force-app-v<version>` tag exists for it); otherwise leave it for the next release
  bump. Don't bump the version here.

## Development process (repo standard: CLAUDE.md, resilient to pauses)

1. **Plan in the repo.**
   - Write this plan to `docs/superpowers/plans/2026-10-04-frm-signal-linking.md`, with a
     **Status** table (stream, worktree id, branch, state).
   - Commit it and push it to `ccr-37b6f575-4lu7ni` before launching any worker.
   - Update the table, then commit and push, at every stream start, finish, review and merge.
2. **Execute on Sonnet 5.5 at medium effort.**
   - Create a local agent definition, `.claude/agents/force-plotting-implementer.md`, with
     frontmatter `model: sonnet`, `effort: medium` and `skills: [force-app-conventions]`. It's local
     only (`.claude/` is gitignored), so its full text is also recorded in the plan doc.
   - Each worker runs with `isolation: "worktree"` from a self-contained brief: the stream section
     and shared contract copied in, the files it owns, the tests to run, and the commit trailers.
   - Workers commit after each logical step and never push, merge or rebase.
   - Run stream **A** alone, then review and merge it into the working branch. Then **B, C and D**
     in parallel (3 workers), each based on the merged A. Then **E**.
3. **Simplify.** After each stream merges, and once at the end, run `/simplify` over the
   branch diff.
4. **Review on Opus at high effort.**
   - Run the `force-app-reviewer` agent (inherits Opus, `effort: high`) and `/code-review high`
     over the full diff.
   - Fix confirmed findings through a Sonnet worker, or directly if they're trivial.
5. **Verify.**
   - Tests, typecheck and lint: run `ci-local`. It covers `npm test` and `npm run typecheck`
     for `@d1/force-plotting` and `force-app-web`, `npm run lint:theme -w force-app-web` and
     `npm run build:extension`.
   - The real UI in headless Chromium, using the `force-app-verify`/`run` setup: sim backend,
     web on :5180, a cut with a live cache. Check:
     - 2D and 3D Lite right-click;
     - the marker, and recentring a zoomed chart;
     - FFT mode switching back to Force;
     - chart hover moving the ring;
     - chart right-click → Show position on map, which pans the map;
     - the crop items reaching Save changes;
     - Copy;
     - Escape and operation-switch clearing;
     - gridded behaviour;
     - Full mode, if an octree is available locally (otherwise the unit tests for
       `octreePathParams` cover it, and the gap is reported).
   - Capture screenshots for the wiki.
6. **PR and merge.**
   - Push the branch and open a PR to `main` (repo template if present; body ends with the
     Claude Code footer).
   - Subscribe to PR activity and drive CI to green.
   - Merge when green and mergeable, as the user asked.
   - After merging, delete the plan file in a follow-up commit (the plans-folder convention) and
     record the spec's Status as Implemented.

**Resuming after a pause:**
- The plan doc's Status table plus `git worktree list` and each worktree's
  `git log <base>..HEAD` are the source of truth (CLAUDE.md *Resuming interrupted work*).
- A stopped worker is resumed with `SendMessage` to its agent id. If that fails, relaunch with the
  same brief pointed at its worktree, plus a summary of what's committed.
