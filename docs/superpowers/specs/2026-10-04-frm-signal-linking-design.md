# FRM ↔ Signals linking

**Date:** 2026-10-04
**Status:** Implemented (PR #121).
**Scope decision:** the Plot dashboard (`ForceDashboard`), which is both the Force App's Plot page
and Directus *Force Analysis*. Lite and Full/Gridded (octree) maps. The Record page is deferred.

## Why

The Signals charts (force against time) and the FRM map (the same samples laid out on the tool
path) show one cut two ways, but the only link between them was that crop edits on the charts
re-cropped the Lite cloud. There was no way to point at a spot on the map and ask "when was
that?", or at a moment on the charts and ask "where was the tool?".

## Decision

**Time is the shared key.** Chart buckets are indexed into `detail.series[a].t`; cloud points
are indexed into the live cache. `idxOfTime()` (`liveCache.ts`) converts between them, and
decimated caches (compare, filtered) keep the true `t`. The dashboard holds one `markTime`
(pinned, not persisted) and derives a `hoverTime` from the chart hover.

- **Map to time.** Right-click a map point: *Show position in time*, *Clear marker*, *Copy point
  info*, *Set crop start/end here*. The marker is drawn on every Force chart; the zoom recentres on
  it when it is off-screen (`recentreWindow`). The crop items reuse `onCropEdit`, so they batch
  into *Save changes*.
- **Time to map.** Hovering an env chart puts a hollow ring on the map; right-click gives *Show
  position on map* (pins the ring and marker, pans the map via `revealTime`). `revealTime` is
  `false` only when there is definitely no drawn sample for that time; a map that is still loading
  queues the request itself and applies it after its first draw with content.
- **Picking, Lite.** The GPU path computes positions in the shader, so a 2D turning-spiral pick
  (GPU, and gridded) replays them on the CPU: `pickSpiral` walks the GPU's own phase-0 samples inside
  the crop and places each with `spiralPositionInto`, the allocation-free form of the shader maths
  (`computeSpiralVertexJS` wraps it). No path is built, so a right-click costs no memory
  proportional to N. The CPU path (`buildCloud`) keeps `Cloud.idx`; 3D and non-spiral clouds scan
  `cloud.pos` through the cloud's matrix. Only a gridded non-spiral 2D path still calls `buildPath()`
  for the one pick. All take the nearest point within a few pixels. A gridded 3D cloud can't be
  resolved to samples and says so.
- **Picking, octree, by position.** Octree points have no time (only x, y and Fx/Fy/Fz). But the
  octree is in the same world frame as Lite's measured mode: mm, centred on the part axis, θ = 0 at
  the cut start (`process_force.m:168-176,227` against the measured branch of `path.ts`), and
  potree-core restores the LAS offset, so coordinates are true mm. It is also built from fixed
  geometry: measured speed, the auto cut start, and the feed and diameter from the `.mat`. That is
  the live cache (its own samples are the auto-cut window, so the window is `t[0]..t[N-1]`, not
  `csSec`/`ceSec`, which only equal them when Time = (n-1)/Fs) with the header's `feed` and `diam`
  plus the analysis row's `pulses_per_rev` and `inner_diameter`. So `octreePathParams()` describes
  the octree's own path, and the cache's samples are streamed through it (`pickSpiral`, stride 1),
  projected through the octree camera and picked. The result is
  the sample (within one cache sample when the cache was decimated above 5M samples). This needs
  the live cache; without it the time items are disabled. In a gridded octree the pick means
  "nearest sample to this spot".
- **Right-click vs right-drag.** Right-drag pans the map (2D Lite as before, Full and 3D through
  OrbitControls), so the menu must only open for a press that doesn't move. `contextmenu` can't
  say (Windows fires it on release, macOS and Linux on press), so the views only `preventDefault()`
  it and open the menu from the right-button `pointerup` when it is within a few pixels of its
  `pointerdown` (`createClickTracker`). Touch long-press therefore no longer opens a menu.
- **Host-agnostic.** The new `ContextMenu.vue` lives in `force-plotting` (invariant 10). No new
  panel type and no change to `RIGHT_KEY` (invariant 11).

Modules: `cloudPick.ts` (contract and pure helpers), `octreePick.ts`, `chartMark.ts`,
`ContextMenu.vue`; wiring in `ForceDashboard.vue`.

## Deferred

- The Record page's live panels.
- A reverse ring for compare-on-octree (only the raw Lite pane's ref is revealed in compare mode).
- Persisting the marker or sharing it between panels.
- Code-quality follow-ups from the final simplify pass, skipped as not worth the churn here: one
  shared pending-reveal helper for FrmCloud and FrmOctree, one shared ring overlay component, and a
  faster 2D pick (reject samples by radius before the trig and projection, and fold the view and
  projection matrices into one multiply). A 5M-sample pick currently takes roughly 0.3–0.5 s.

## Pre-existing, found during review

Fixed. Since 5e3876a FrmCloud never read `Cloud.zv` (`buildCloud` writes z = 0 when a Z series is
set), so the Lite 3D view rendered flat. `FrmCloud.rebuild` now calls `withHeight` (liveCloud.ts),
which bakes `zv` into `pos` z. The 3D pick, the hover/selection rings and the map ↔ signals marker
all read `cloud.pos` through the same model matrix, so they stay aligned with the displaced points.

## Side finding

`saveCropAsOfficial` (`ForceDashboard.vue`) re-queues the octrees after a crop is saved, but the
orchestrator ignores the crop override, so the rebuilt octree still uses the auto crop. Out of
scope here; octree picking assumes the auto crop, which is what the octree really uses.
