# FRM ↔ Signals linking

**Date:** 2026-10-04
**Status:** Implemented on branch `ccr-37b6f575-4lu7ni`, pending merge.
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
  position on map* (pins the ring and marker, pans the map via `revealTime`).
- **Picking, Lite.** The GPU path computes positions in the shader, so the CPU rebuilds them with
  `buildPath()` (as `refineGpuPointCount` already did) and picks against those. The CPU path
  (`buildCloud`) now keeps `Cloud.idx`. Both project through the camera and take the nearest point
  within a few pixels. A gridded 3D cloud can't be resolved to samples and says so.
- **Picking, octree, by position.** Octree points have no time (only x, y and Fx/Fy/Fz). But the
  octree is in the same world frame as Lite's measured mode: mm, centred on the part axis, θ = 0 at
  the cut start (`process_force.m:168-176,227` against the measured branch of `path.ts`), and
  potree-core restores the LAS offset, so coordinates are true mm. It is also built from fixed
  geometry: measured speed, the auto cut start, and the feed and diameter from the `.mat`. That is
  the live cache header (`csSec`, `ceSec`, `feed`, `diam`) plus the analysis row's
  `pulses_per_rev` and `inner_diameter`. So `octreePathParams()` rebuilds the octree's own path from
  the live cache, and the samples are projected through the octree camera and picked. The result is
  the sample (within one cache sample when the cache was decimated above 5M samples). This needs
  the live cache; without it the time items are disabled. In a gridded octree the pick means
  "nearest sample to this spot".
- **Host-agnostic.** The new `ContextMenu.vue` lives in `force-plotting` (invariant 10). No new
  panel type and no change to `RIGHT_KEY` (invariant 11).

Modules: `cloudPick.ts` (contract and pure helpers), `octreePick.ts`, `chartMark.ts`,
`ContextMenu.vue`; wiring in `ForceDashboard.vue`.

## Deferred

- The Record page's live panels.
- A reverse ring for compare-on-octree (only the raw Lite pane's ref is revealed in compare mode).
- Persisting the marker or sharing it between panels.

## Side finding

`saveCropAsOfficial` (`ForceDashboard.vue`) re-queues the octrees after a crop is saved, but the
orchestrator ignores the crop override, so the rebuilt octree still uses the auto crop. Out of
scope here; octree picking assumes the auto crop, which is what the octree really uses.
