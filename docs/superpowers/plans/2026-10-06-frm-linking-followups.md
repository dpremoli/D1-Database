# FRM ↔ Signals linking — follow-ups (items 5, 6, 7, 8)

**Branch:** `ccr-37b6f575-4lu7ni` (restarted from `main` 5eb67da) · **Spec:** `docs/superpowers/specs/2026-10-04-frm-signal-linking-design.md`
(updated in stream C) · **Origin:** the "still missing" check after #121/#122.

| # | Item | Fix |
|---|---|---|
| 8 | Code-quality follow-ups skipped in #121 | One pending-reveal helper; one ring overlay component; a faster pick (radius cull before trig, one folded projection matrix) |
| 5 | Touch long-press no longer opens a menu | Long-press (one finger, held still ~500 ms) opens the map and chart menus |
| 7 | Saving an official crop re-queues the octrees, but the host ignores the override | Orchestrator passes the crop to MATLAB for octree and grid builds; MATLAB cuts there |
| 6 | Octree picks drift if `inner_diameter` / `pulses_per_rev` (or diameter) change after the build | The build publishes `d1_build.json` (the geometry it actually used); the map reads it |

## Status

| Stream | Worktree / agent | Branch | State |
|---|---|---|---|
| A — frontend: 8 + 5 (plotting helpers, FrmCloud, FrmOctree, ForceChart) | `.claude/worktrees/agent-aca1979536c1574bf` | `worktree-agent-aca1979536c1574bf` | reviewed, merged |
| B — host: 7 + 6 (orchestrator, process_force.m, tests) | `.claude/worktrees/agent-a6cc7b906792cc93b` | `worktree-agent-a6cc7b906792cc93b` | reviewed, merged (MATLAB unexecuted — backlog) |
| C — frontend: consume `d1_build.json`, dashboard, docs, backlog (after A and B) | `.claude/worktrees/agent-acf389501a9318a9d` | `worktree-agent-acf389501a9318a9d` | reviewed, merged |
| Simplify / Opus review / verify | `.claude/worktrees/agent-a40c434666b0f36a9` (review fixes) | `worktree-agent-a40c434666b0f36a9` | simplify done; Opus review done — fixes in progress (Sonnet worker) |
| PR + merge | coordinator | — | not started |

Workers: `.claude/agents/force-plotting-implementer.md` (Sonnet, medium effort — the user's
choice), in their own worktree, commit per step, never push/merge/rebase. Coordinator merges
after review, then `/simplify`, Opus review (`force-app-reviewer` + `/code-review high`), fixes,
`ci-local`, `plot_link_smoke.mjs`, PR, merge. Commit trailers for workers:

```
Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WcXKoSEkcV3VPjR2tsnatc
```

## Shared contract: the octree build manifest (B writes, C reads)

The published octree directory (`OCTREE_DIR/<op>/` and `OCTREE_DIR/grid/<op>/`, served at
`/octrees/<path>/`) gains **`d1_build.json`**:

```json
{
  "schema": 1,
  "kind": "octree",              // or "grid"
  "speed_mode": "measured",      // the octree is always integrated from the tacho
  "feed": 0.05,                  // mm/rev actually used
  "diam": 80.0,                  // mm actually used (after any outer_diameter override)
  "inner_diam": 0.0,             // mm actually used
  "ppr": 1,                      // pulses per rev actually used
  "cut_start_sec": 0.264,        // t (the file's Time column) of the first octree sample: theta = 0 here
  "cut_end_sec": 3.867,          // t of the last octree sample
  "crop_source": "auto",         // "auto" (findchangepts) or "override" (the official crop)
  "n_points": 18015,
  "built_at": "2026-10-06T12:00:00Z"
}
```

`cut_start_sec`/`cut_end_sec` are on the same axis as the live cache's `t` (both are the file's
Time column), so the map anchors with `spiralAnchor(cache, cut_start_sec)` exactly as Lite does.
Absent file (octrees built before this change) ⇒ today's behaviour (cache window + row values).

## Stream A — frontend: 8 + 5

Files: `packages/force-plotting/src/{cloudPick.ts,cloudPick.test.ts,frmCloudShader.ts,frmCloudShader.test.ts,FrmCloud.vue,FrmOctree.vue,ForceChart.vue,index.ts}` plus new `mapProjector.ts`(+test), `LinkRings.vue`, `pendingReveal.ts`(+test) (names may differ; keep them small and pure where possible). Do not touch `ForceDashboard.vue` or `octreePathParams` (stream C).

1. **Pending reveal helper** — the "hold a requested reveal until the view is ready, drop it when
   the cut changes" state machine is written twice (FrmCloud `pendingReveal`/`applyPendingReveal`
   and FrmOctree's). Extract one tiny pure helper (e.g. `createPendingReveal()` with `hold(t)`,
   `drop()`, `take()`), unit-test it, use it in both. Behaviour unchanged.
2. **One ring overlay** — FrmCloud and FrmOctree each render the pin/hover rings with copied
   `.fc-ring` CSS. Make one `LinkRings.vue` (props `pin`, `hover`: `{x,y}|null`) with the CSS, used
   by both. Look unchanged (FrmCloud's current style).
3. **Faster pick** —
   - `mapProjector.ts`: given a THREE camera (+ optional model matrix), CSS size, build ONE folded
     4×4 (projection × view [× model]) per pick and project `(x,y,z)` with a single inlined
     multiply + divide into a reused `{px,py}`; null when off-clip. Unit-test against
     `Vector3.applyMatrix4(m).project(camera)` (ortho and perspective). Use it in both views' picks
     and rings instead of per-sample `Vector3.project`.
   - `pickSpiral` gains an optional cull: when the caller passes the click's world point and a world
     radius (2D flat views only: Lite 2D, octree flat), skip a sample whose `rho` differs from the
     click's radius-from-axis by more than the world radius, before the cos/sin and projection.
     Split `spiralPositionInto` so rho is available before theta (keep the shader-lockstep tests).
     Prove with a test that the culled pick returns the same sample as the unculled one across
     modes (measured/rpm/vc), strides and a donut.
4. **Touch long-press (item 5)** — extend `createClickTracker` (or add `createPressTracker`) so a
   single-finger touch held within the slop for ~500 ms fires a callback with the client point;
   cancelled by movement beyond the slop, a second pointer, pointerup or pointercancel; after it
   fires, that touch's later pointerup does nothing else. Unit-test with fake timers. Wire it in
   FrmCloud (2D and 3D), FrmOctree and ForceChart (env charts with `menu`; it emits `chartmenu`
   like a right-click). Keep right-click-vs-drag behaviour exactly as is. Note: canvases already
   have `touch-action: none` and `contextmenu` is `preventDefault`ed.

Checks: `npm test` + `npm run typecheck` for `@d1/force-plotting` and `force-app-web`,
`npm run lint:theme -w force-app-web`, `npm run build:extension` (run `npm ci` in the worktree
first).

## Stream B — host: 7 + 6

Files: `scripts/matlab/process_force.m`, `scripts/matlab/test_octree_out.m` (or a new
`test_crop_window.m`), `scripts/force_orchestrator.py`, new/extended `tests/scripts/test_*.py`.

1. **MATLAB crop option (7)** — new optional opts `crop_start_sec`, `crop_end_sec` (seconds on the
   file's Time axis `t`). After the auto `cutstart` is found (~:157-164): if `crop_start_sec` is
   set, `cutstart = find(t >= crop_start_sec, 1)` (fallback: keep auto). After `cutend` (~:175):
   if `crop_end_sec` is set, `cutend = min(cutend, find(t <= crop_end_sec, 1, 'last') - cutstart + 1)`
   (guard ≥1). Everything downstream (octree D1OC, grid D1GR, PNG, cache) follows. Record
   `crop_source` = "override" when either applied.
2. **MATLAB build manifest (6)** — when `octree_out` / `grid_out` is set, write a JSON next to it
   (`<octree_out>.json`, `<grid_out>.json`) with `feed, diam, inner_diam, ppr, cut_start_sec =
   t(cutstart), cut_end_sec = t(abs_cut_end), crop_source, speed_mode:'measured'` — the values
   the spiral was actually integrated with (`jsonencode`).
3. **Orchestrator (7)** — `claim_octree` and `claim_grid` also return `crop_start_idx_override`,
   `crop_end_idx_override`, `sample_rate`; `process_octree_row` / `process_grid_row` pass
   `crop_start_sec = idx / sample_rate` (and end) in `opts` when set (the dashboard writes
   `round(sec*Fs)` and reads `idx/Fs`, so this round-trips). Do NOT pass them in `process_file`
   (summary `cut_*_idx` stays the auto window) or the diag path.
4. **Orchestrator (6)** — after a successful build, read the MATLAB JSON, add `schema:1, kind,
   n_points, built_at`, and publish it as `d1_build.json` in the same directory as `metadata.json`
   (both octree and grid). If the MATLAB JSON is missing, publish no `d1_build.json` and log a
   warning (the client falls back to today's behaviour).
5. **Tests** — pytest with the subprocess/MATLAB call stubbed: claim returns the new columns; opts
   carry `crop_start_sec/crop_end_sec` only when overrides are set; manifest is written with the
   contract's keys; `process_file` opts never carry crop keys. MATLAB: extend `test_octree_out.m`
   (manual, MATLAB isn't in CI) to assert the crop window and the JSON — and add these to the
   physical-test backlog in stream C.

Checks: `python -m pytest tests/scripts -q` (needs `pip install -r scripts/requirements.txt pytest
requests "numpy==2.2.*" "scipy==1.14.*" "scikit-learn==1.5.*"`; DB-level tests may skip locally),
`pre-commit run --files <changed>` (ruff, ruff-format).

## Stream C — frontend consumption + docs (after A and B merge)

Files: `packages/force-plotting/src/{FrmOctree.vue,cloudPick.ts(+test),ForceDashboard.vue}`,
`docs/superpowers/specs/2026-10-04-frm-signal-linking-design.md`, `docs/wiki/force-app/plot-dashboard.md`,
`docs/runbooks/physical-test-backlog.md`, `apps/force-app/web/src/changelog.ts`.

1. FrmOctree fetches `${base}d1_build.json` (no-store, like `metadata.json`), tolerant of 404 and
   malformed JSON (fall back to today's behaviour). Load token guards it like `loadMeta`.
2. `octreePathParams(c, innerDiam, ppr, build?)` uses the manifest's `feed, diam, inner_diam, ppr`
   and window `[cut_start_sec, cut_end_sec]` when present. If `cut_start_sec < c.t[0]` (the crop
   starts before the cache covers), the anchor can't be placed: the octree view emits
   `reason: 'outside-cache'` (extend the reason union) and rings/reveal return false/hidden.
3. FrmOctree exposes `timeWindow(): {start,end}|null` (the mappable window = build window ∩ cache);
   the dashboard's chart-menu hint uses it ("Outside the mapped window").
4. `saveCropAsOfficial`: also re-queue an octree whose status is `error`; keep leaving
   `pending`/`processing` alone, but add a one-line note in the confirmation that a build already
   running finishes on the old window.
5. Docs: spec (Deferred/side-finding sections updated: 5, 6, 7, 8 done; manifest described), wiki
   (long-press; Full uses the official crop after rebuild), changelog note (0.1.x unreleased top
   entry, if untagged), physical-test backlog entries: MATLAB crop + manifest on d1-server; octree
   pick alignment on a real archived cut (with and without an official crop); touch long-press on a
   touchscreen.

## Review fixes (Opus review: force-app-reviewer + /code-review high)

One worker, files: everything this plan touched. Each fix with a test where the repo can test it.

1. **Exact octree anchor (float32 + decimation).** The cache's `t` is float32; the manifest's
   `cut_start_sec` is a double, so `idxOfTime` can skip `t[0]` (≈48% of starts) and, with a
   decimated cache (`step` ≥ 2) or an override start between cache samples, the anchor lands up
   to `step-1` raw samples late. Fix: MATLAB adds `revs_cs` to the build JSON — the cumulative
   revolutions at `cutstart` in **the same units as the live cache's `revs` array** (check how
   `write_live_cache` derives it, e.g. `revs_cum`, and whether PPR is applied there) — and the
   orchestrator passes it through into `d1_build.json` (an optional key: schema stays 1; the
   parser accepts manifests without it). The client then uses `{ tCs: cut_start_sec, revsCs:
   revs_cs }` as the spiral anchor (no cache lookup), which is exact for any decimation and also
   lets an override that starts before the cache map the overlapping part (window = build ∩
   cache; `outside-cache` only when they don't overlap). Without `revs_cs` (older manifests):
   compare/anchor with `Math.fround(cut_start_sec)` / `Math.fround(cut_end_sec)` so a float32
   `t[0]` equal to the rounded start is included. Tests: a Float32Array cache with `t = k/Fs`
   (non-representable), decimated, override mid-step, override before the cache.
2. **MATLAB crop as one unit.** Apply `crop_end_sec` only if the start was applied or no start was
   given; set `crop_source = 'override'` only when a value actually changed the window. Make
   `test_octree_out.m`'s degenerate case consistent.
3. **Crop saved during a build.** In the orchestrator's octree and grid "done" UPDATEs, set the
   status to `'pending'` (and keep the requested_at fresh) instead of `'done'` when the row's
   `crop_start_idx_override` / `crop_end_idx_override` are `IS DISTINCT FROM` the values claimed —
   so a crop saved while `processing` (or while the dashboard thought `pending`) gets its rebuild.
   Update the dashboard note in `saveCropAsOfficial` accordingly ("rebuilds after the current
   build"). pytest for the SQL params.
4. **Manifest required and ordered.** MATLAB always writes the build JSON, so a missing/unreadable
   one fails the build (`octree_status='error'` with a clear message) instead of publishing an
   octree whose fallback geometry may be wrong. Write `d1_build.json` before `metadata.json` (a
   client that sees metadata also sees the manifest); remove any stale `d1_build.json` before
   publishing. pytest.
5. **Long-press robustness.** `createLongPress.down`: an `isPrimary` touch starts a new gesture —
   clear the stale pointer set first. Call `longPress.cancel()` in FrmCloud's `teardownRenderer`
   and FrmOctree's `teardownGL` (canvas swaps lose pointerups). In ForceChart only swallow a
   `contextmenu` for touch (`(ev as PointerEvent).pointerType !== 'mouse'` and `longPress.touching`),
   never a mouse right-click. Tests.
6. **Loading reason.** While the manifest fetch is pending, FrmOctree's pick emits a new reason
   `'loading'` (add to the union) and the dashboard hint says "The map is still loading" — not
   "Needs this cut's live cache".
7. Spec + backlog text updated for `revs_cs`, the re-queue-on-done rule and the required manifest.
