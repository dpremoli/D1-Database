# UX larger items — 2026-10-06

Implements the "Larger" tier of
[`docs/reviews/2026-10-05-ux-utility-review.md`](../../reviews/2026-10-05-ux-utility-review.md):
D5 (sample timeline), D11 (campaign overview), P10 (diagnostics across a campaign), P6 (cutting
metrics) and R9 (captures list search, filters and bulk actions). Delete this plan once the batch
has shipped (see `docs/superpowers/README.md`).

**Process.** As before, with one addition for size: each stream **first writes a short design
spec** in `docs/superpowers/specs/2026-10-06-<topic>-design.md` (problem, options weighed, decision,
data flow, what is out of scope; one to two pages) and adds a row to the specs table in
`docs/superpowers/README.md`, commits it, then implements against it. Four Sonnet streams in
worktrees (each fast-forwarded to the plan commit first), commits after each step, no pushes by
workers. Then an Opus `/simplify` pass, a high-effort Opus review, fixes, an Opus re-review, local
CI including `pre-commit`, PR, CI green, merge. Every check that needs the rig or a live Directus
goes into [`docs/runbooks/physical-test-backlog.md`](../../runbooks/physical-test-backlog.md) in
the same stream (see `CLAUDE.md`).

## Status

| Stream | Items | Worktree / branch | State |
|---|---|---|---|
| M — Sample timeline and campaign overview | D5, D11 | `agent-a8bd81e18c8eeb71e` | merged; new `d1-trace` endpoint; no schema change |
| N — Diagnostics across a campaign | P10 | `agent-a72215e01a6e621f0` | merged; picker still loads all rows (P12); campaign read permission for non-admins unchecked |
| O — Cutting metrics | P6 | `agent-a1b290277d7c04730` | merged; axis mapping (Fc=Fz, Ff=Fx, Fp=Fy) is an assumption, selectable in the card |
| P — Captures list | R9 | `agent-ab5dd77bae769b66f` | in progress |
| /simplify (Opus) | all | — | not started |
| /code-review high (Opus) | all | — | not started |

## M. Sample timeline and campaign overview — D5, D11

Files: `core/extensions/d1-lab-dashboard/**` (SampleDashboard.vue and a new timeline component), a
small endpoint for the trace functions (extend `d1-next-number`'s pattern or a new
`d1-trace` endpoint extension; not `d1-ask-endpoint`), `core/extensions/d1-campaign-ops/**`, a
migration only if a function or view is truly needed (use `db-migration`), tests, the database
wiki pages.

- **D5 — Sample timeline.** A "Timeline" tab on the Sample dashboard built from
  `f_sample_timeline`, `f_trace_ancestors`, `f_trace_descendants` and `f_trace_stock_origins`
  (`db/migrations/20260619000014_traceability.sql`): stock lot → parents → this sample →
  operations and tests in date order → children. Each node links to its record. The endpoint runs
  the functions but only returns rows the caller can read (check each referenced record through
  `ItemsService` with `req.accountability`, or filter by ids the user can read); it never leaks a
  sample a role cannot see. Signed-in users with app access only.
- **D11 — Campaign overview.** `CampaignOps.vue` today lists operations only. Add an overview
  panel: the campaign's samples, their operations, their test sessions and each cut's
  force-analysis status (crawler/diag state), with counts and simple progress (operations done
  vs. planned if the schema has a planned count; otherwise just counts). Add "Add samples" and
  "Add test sessions" pickers if the campaign tables support those links (check
  `campaign_samples` and friends); otherwise say so in the spec.

## N. Diagnostics across a campaign — P10

Files: `packages/force-plotting/src/**` (`RecipeLibrary.vue`, `DiagnosticsWorkbench.vue`,
`diagRecipes.ts`), `apps/force-app/web/src/force/DiagnosticsPage.vue` and siblings, tests, the
diagnostics wiki page. Read how a build is requested today (`diag_status` → pending, the diag
service and host orchestrator).

- Replace `window.prompt` / `window.confirm` in the recipe library with proper in-app dialogs
  (save-as with name and notes, rename, delete confirm), and add recipe import/export as JSON and
  a "modified since loaded" badge.
- Replace the flat `<select>` picker (`DiagnosticsPage.vue` ~143, `limit: -1`) with a searchable
  list grouped by sample/campaign, with "Needs build" / "Built" / "Error" filters and Open in Plot
  / Open in Directus links.
- "Apply recipe to selected": multi-select operations and queue a build of the chosen recipe for
  each (the same request the single Build button makes, one per operation, with progress and a
  summary of what was queued, skipped or refused). Never rebuild something already built with the
  same recipe hash unless asked.

## O. Cutting metrics — P6

Files: `packages/force-plotting/src/**` (a new `cuttingMetrics.ts`, `ForceDashboard.vue` signal
statistics area, `statsCsv.ts`), tests, the Plot-dashboard wiki page. No schema change unless the
spec argues for one.

- A "Cutting metrics" card next to Signal statistics for the cropped window: resultant |F| (mean,
  peak), tangential/feed/radial components (Fc/Ff/Fp) from the axis mapping the turning geometry
  already uses (`angle.ts` and friends; document the mapping), cutting power Pc ≈ Fc·vc with
  vc = π·D·n, and specific cutting energy kc ≈ Fc / (ap·f). Feed, depth, diameter and RPM come from
  the operation fields the dashboard already fetches. Show units, show "—" with a reason when an
  input is missing, and include the metrics in the stats CSV.
- Pure functions with unit tests on synthetic signals with known answers.

## P. Captures list — R9

Files: `apps/force-app/web/src/settings/CapturesSettings.vue` (+ a new small module for list
logic), `apps/force-app/backend/app/**` for `/captures/browse` paging/filtering if needed, tests,
the Settings wiki page.

- Search box (name, sample, date), status filter chips (not uploaded / incomplete / uploaded),
  sort by date or size, and paging or "load more" instead of the silent 500 cap (say how many
  there are in total).
- Multi-select with bulk delete (confirmed, listing what will be deleted and the space freed) and a
  "Free up space: delete uploaded captures older than N days" action that never touches
  not-uploaded or incomplete captures.
- `uploadAllUnsynced` shows progress (n of m, current item) and can be cancelled between items.
- Backend: if filtering/paging belongs server-side, add query params to `/captures/browse` with
  tests; deletes go through the existing delete endpoint and its safety checks.

## Commit trailers

```
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPnGB1Ei8ENvWMdAxmthpu
```
