# FRM ↔ Signals linking

**Date:** 2026-10-04
**Status:** Implemented (PR #121); follow-ups (touch long-press, faster picks, the official crop and the build manifest) in `docs/superpowers/plans/2026-10-06-frm-linking-followups.md`. The MATLAB side is not executed anywhere automated: see the physical-test backlog.
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
  the cut start (`process_force.m`, the octree path against the measured branch of `path.ts`), and
  potree-core restores the LAS offset, so coordinates are true mm. It is built from fixed geometry:
  measured speed, the cut window, and the feed, diameters and ppr it was integrated with. The
  cache's samples streamed through that same geometry (`octreePathParams()`, `pickSpiral` at stride
  1) land on the octree's points; they are projected through the octree camera and picked. The
  result is the sample (within one cache sample when the cache was decimated above 5M samples). This
  needs the live cache; without it the time items are disabled. In a gridded octree the pick means
  "nearest sample to this spot".
- **The build manifest.** Which geometry? The analysis row's `inner_diameter`, `pulses_per_rev` and
  the official crop can all be edited after a build, and the live cache's window is the auto cut,
  so reconstructing from the row would drift. Instead the host publishes **`d1_build.json`** next
  to `metadata.json` in both the octree and grid directories (`scripts/force_orchestrator.py`,
  `_publish_build_manifest`; MATLAB writes the values it really used): `schema: 1`, `kind`,
  `speed_mode`, `feed`, `diam`, `inner_diam`, `ppr`, `cut_start_sec` / `cut_end_sec` (on the same
  axis as the live cache's `t`, so `spiralAnchor(cache, cut_start_sec)` anchors it exactly as
  Lite does), `crop_source` (`auto` or `override`), `n_points`, `built_at`. `FrmOctree` fetches it
  (`no-store`) and `parseOctreeBuild()` accepts it only when well formed (schema 1, finite numbers,
  `ppr > 0`, end >= start); `octreePathParams(c, innerDiam, ppr, build)` then uses the manifest's
  values and window instead of the row's. **Fallback:** an octree built before the manifest has none
  (404), or the file is malformed: the map uses the cache window and the row's values, as before.
  **Outside the cache:** if the build's cut start is before the cache's first sample (the cache
  holds a later window), the anchor has no sample: picks answer `reason: 'outside-cache'` ("The live
  cache doesn't cover this octree's crop"), rings hide and reveal returns false. `timeWindow()`
  (the build window within the cache's `t` range) feeds the chart menu's "Outside the mapped window"
  hint.
- **Official crop in the octrees.** The orchestrator passes the saved crop override
  (`crop_start_idx_override / sample_rate`, likewise the end) to MATLAB for octree and grid builds
  only, and MATLAB cuts there (`crop_start_sec` / `crop_end_sec` options); the summary's `cut_*_idx`
  and the diagnostics path keep the auto window. So after saving an official crop and the rebuild,
  Full and Gridded show the same window as the charts and Lite. `saveCropAsOfficial` re-queues
  `done` and `error` builds; a build already running finishes on the old window and the confirmation
  says so. **Not yet exercised:** the MATLAB changes have never run (no MATLAB in CI or the cloud
  session); the backlog item must be ticked before relying on them.
- **Right-click vs right-drag.** Right-drag pans the map (2D Lite as before, Full and 3D through
  OrbitControls), so the menu must only open for a press that doesn't move. `contextmenu` can't
  say (Windows fires it on release, macOS and Linux on press), so the views only `preventDefault()`
  it and open the menu from the right-button `pointerup` when it is within a few pixels of its
  `pointerdown` (`createClickTracker`).
- **Touch long-press.** A single finger held still for ~500 ms (within a 10 px slop) opens the same
  menus: on the map (Lite 2D and 3D, Full) and on the env charts (`longPress.ts`). Moving, a
  second finger, lifting or a cancel aborts it. The menu opens slightly down-right of the finger
  (`TOUCH_MENU_OFFSET_PX`) so the finger doesn't hide it; the pick stays under the finger.
- **Host-agnostic.** The new `ContextMenu.vue` lives in `force-plotting` (invariant 10). No new
  panel type and no change to `RIGHT_KEY` (invariant 11).

Modules: `cloudPick.ts` (contract and pure helpers), `octreeBuild.ts` (manifest parser and window),
`mapProjector.ts` (one folded projection per pick), `longPress.ts`, `pendingReveal.ts`,
`LinkRings.vue`, `chartMark.ts`, `ContextMenu.vue`; wiring in `ForceDashboard.vue`.

## Deferred

- The Record page's live panels.
- A reverse ring for compare-on-octree (only the raw Lite pane's ref is revealed in compare mode).
- Persisting the marker or sharing it between panels.

Done since: the shared pending-reveal helper, one ring overlay component and the faster pick
(radius cull before the trig, one folded projection matrix), touch long-press, the official crop in
the octree builds and the build manifest (see above).

## Pre-existing, found during review

Fixed. Since 5e3876a FrmCloud never read `Cloud.zv` (`buildCloud` writes z = 0 when a Z series is
set), so the Lite 3D view rendered flat. `FrmCloud.rebuild` now calls `withHeight` (liveCloud.ts),
which bakes `zv` into `pos` z. The 3D pick, the hover/selection rings and the map ↔ signals marker
all read `cloud.pos` through the same model matrix, so they stay aligned with the displaced points.

## Side finding

Fixed. `saveCropAsOfficial` (`ForceDashboard.vue`) re-queued the octrees after a crop was saved, but
the orchestrator ignored the crop override, so the rebuilt octree still used the auto crop. The
override now reaches the octree and grid builds (see "Official crop in the octrees"), and the
manifest tells the map which window a given octree really has.
