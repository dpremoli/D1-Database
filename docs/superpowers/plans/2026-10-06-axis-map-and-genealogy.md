# Cutting-metrics axis map and genealogy functions — 2026-10-06

Two follow-ups from PR #127. Delete this plan once the batch has shipped (see
`docs/superpowers/README.md`).

**Process.** Two Sonnet streams in worktrees (each fast-forwarded to the plan commit first),
commits after each step, no pushes by workers. Then an Opus `/simplify` pass, a high-effort Opus
review, fixes, an Opus re-review, local CI including `pre-commit`, PR, CI green, merge. Checks that
need the rig or a live Directus go into `docs/runbooks/physical-test-backlog.md`.

## Status

| Stream | Items | Worktree / branch | State |
|---|---|---|---|
| Q — Axis map | P6 follow-up | — | not started |
| R — Genealogy functions | f_trace_* rewrite | — | not started |
| /simplify (Opus) | all | — | not started |
| /code-review high (Opus) | all | — | not started |

## Q. Cutting-metrics axis map

The owner's standard: **Fc = Fx, Fp = Fz** (so Ff = Fy). The mapping can change with workholding
and the machining operation, so it stays selectable.

- Change `DEFAULT_AXIS_MAP` in `packages/force-plotting/src/cuttingMetrics.ts` to
  `{ Fc: 'Fx', Ff: 'Fy', Fp: 'Fz' }`.
- Remember the chosen mapping **per operation subtype** (e.g. MT-F, MT-O) instead of once per
  browser: a stored map `subtype → mapping`, falling back to the default. Migrate the existing
  single `d1.cuttingAxisMap` value sensibly (drop it: it was chosen against the old default).
- The card states which mapping is in use and that it depends on workholding and operation; the
  CSV keeps its `axis_map` column. Update the spec, wiki and the physical-test backlog item
  (confirm per workholding/operation on the rig).

## R. Genealogy functions visit each sample once

`f_trace_ancestors` / `f_trace_descendants` (`db/migrations/20260619000014_traceability.sql`)
recurse with `UNION ALL` and a path-array cycle guard, so they enumerate every **path**: a diamond
lattice of N generations yields ~2^N rows and a 24-level ladder ran > 2 min with > 10 GB of temp.

- New migration (use `db-migration`, then `migration-review`) that `CREATE OR REPLACE`s both
  functions with the **same signature and columns** (depth, sample_id, sample_code, form,
  relationship_type, fraction, path), returning **one row per sample** at its minimum depth with
  one shortest path (deterministic tie-break, e.g. lowest relationship id / sample id). Use an
  iterative breadth-first walk with a visited set (plpgsql) or an equivalent CTE that cannot
  enumerate paths; keep STABLE; keep cycle safety. Down restores the old definitions verbatim.
- Check every caller still works: `f_trace_stock_origins`, `f_sample_timeline`, migration 015
  (AI readiness grants), the `d1-trace` endpoint (its dedupe and deadline stay as defence in
  depth; simplify only if clearly safe), `tests/phase7_traceability.sh`, d1-report if it uses them.
- Tests: extend `tests/phase7_traceability.sh` (or the phase test that covers these functions) with
  a diamond (A→B, A→C, B,C→D → A once at depth 2) and a 30-level ladder that must finish in under
  a second; prove up/down/up on Postgres 16.

## Commit trailers

```
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPnGB1Ei8ENvWMdAxmthpu
```
