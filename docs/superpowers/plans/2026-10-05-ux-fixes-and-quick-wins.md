# UX fixes and quick wins — 2026-10-05

Implements the "Fix first" items and the "Small, high-value" batch from
[`docs/reviews/2026-10-05-ux-utility-review.md`](../../reviews/2026-10-05-ux-utility-review.md)
(item ids X*, R*, P*, D* refer to that review). Delete this plan once the batch has shipped
(see `docs/superpowers/README.md`).

**Process.** Four implementation streams run in parallel on Sonnet, each in its own worktree.
Then an Opus `/simplify` pass and an Opus `/code-review` at high effort over the merged result.
The coordinator merges each stream after reading its diff. Workers commit early, one commit per
item, and never push, merge or rebase.

**Out of scope here:** X3 (already fixed by migration `20261003000132`; the export-control row
filter is a Phase 9 owner decision) and retiring `core/permissions.json` / `core/apply.sh`
(2026-10-03 review decision 4.3, an owner decision).

## Status

Update this table when a stream starts, finishes, is reviewed or is merged (see "Resuming
interrupted work" in `CLAUDE.md`). Each stream runs in its own worktree under
`.claude/worktrees/`, based on `77ea014` (the commit that adds this plan; the harness created them on `73a8547` and the coordinator fast-forwarded them before any edits). Branches are `worktree-agent-<id>`.

| Stream | Items | Worktree / branch | State |
|---|---|---|---|
| A — force-plotting | X1, P1 | `agent-aa316adf0059bce0c` | merged (`6d185f6`); follow-up: pass `opTag` to `DiagnosticsWorkbench` from the web app |
| B — Record page | R1, R3, X4 | `agent-ac917adcb6fa3ab1d` | merged (`6e72287`) |
| C — Ask-DB | D1, D2 | `agent-a70084c335c3236ae` | merged; coordinator dropped the export-controlled example chip |
| D — Directus data entry | X2, D7, D9 | `agent-a5e617bc0453549e7` | merged; migrations 133, 134 proven up/down/up on Postgres 16; new endpoint `d1-next-number` |
| /simplify (Opus) | all | main checkout | done (`919c226`, `be49e5f`) |
| /code-review high (Opus) | all | read-only reviewers | done: force-app 1 blocker (Replay overwrote the remembered setup) + 3 should-fix + 4 nits, fixed in worktree `agent-a722afb90ca2eecfc` (merged `6afe18b`) and `344413f`; Directus/db 0 blockers, 4 should-fix + nits fixed `dd2cf75`..`302cd23`. Opus re-review of the fixes: 0 blockers, 2 should-fix + 3 nits, fixed in `a41c299`, `c83a551`, `5440ba1`/`2a9c612`. **Batch complete on `ccr-567582b5-tmq1ec`; not yet merged to main (no PR opened).** |

## A. force-plotting — X1, P1

Files: `packages/force-plotting/src/**` (`FrmCloud.vue`, `ForceDashboard.vue`, `WearTrend.vue`,
`ClusterTable.vue`, signal-statistics UI, a new small CSV helper module, `index.ts`), their tests,
and `docs/wiki/force-app/` pages for the Plot dashboard.

- **X1 — Lite 3D "Z = Fx/Fy/Fz" renders flat.** `FrmCloud.vue` stopped reading `Cloud.zv` in
  `5e3876a`. Wire `zv` back into the vertex positions so the 3D view has height again, keep the
  pick and the octree/Lite rings aligned with the displaced points, and add a regression test that
  fails on the current code. See the "Pre-existing" section of
  `docs/superpowers/specs/2026-10-04-frm-signal-linking-design.md`.
- **P1 — CSV export.** A shared helper (`toCsv(rows, columns)` with proper quoting, plus a
  `downloadText(filename, text, mime)` that reuses whatever the FRM PNG download already does in
  `frmExport.ts` / `ForceDashboard.vue`). Add "Download CSV" (and "Copy" where cheap) to: Signal
  statistics, Wear trend points, and the Diagnostics cluster table. Header rows carry units.
  Filenames include the operation tag. Unit-test the CSV helper (quoting, commas, newlines,
  NaN/null).
- Tests: `npm run test -w @d1/force-plotting`, `npm run typecheck` / build if the package has one.
  Run the `force-app-reviewer` checklist mentally (invariants in `.claude/agents/force-app-reviewer.md`
  if present).

## B. Record page — R1, R3, X4

Files: `apps/force-app/web/src/record/workspace.ts`, `record/panels/RecordingOptions.vue`,
`record/panels/MachineOperatorPanel.vue` (if needed), a new `record/setupPrefs.ts` (mirroring
`plotPrefs.ts`), their tests, `docs/wiki/force-app/recording.md`, and the in-app changelog
(`changelog.ts`) entry for the next version if the repo adds entries per change.

- **R1 — Remember the setup across launches.** Persist `cfg` (rpm, feed, diam, inner_diam,
  sample_rate, ppr), `link` (sample/equipment/operator ids and labels) and the non-per-cut parts of
  `meta`/`machining` (op_type, insert, edge_id, coolant, axial/radial doc, cutting length, coolant
  pressure) to localStorage, debounced 250 ms and flushed on page hide, parsed defensively field by
  field like `plotPrefs.ts`. Do not persist per-cut fields (notes, operation/pass code, sequence,
  chips ref, chips collected, new_edge). Do not let a restored link fight the Replay-mode clearing
  in `setSource()`. Drop the fake `SIM-CUT-001` default for NI-DAQ (keep a sim default only if
  something depends on it). Add a "Clear setup" control.
- **R3 — "New" carries stale per-cut fields.** In `newRun()` increment `operation_sequence` when it
  is numeric, clear `chips_ref`, `chips_collected` and `new_edge`, so the next Cut ID does not
  repeat. Resolve the TODO at `RecordingOptions.vue:295` if it is small (auto-generate the chips
  ref from the cut id); otherwise leave it and say why.
- **X4 — Stale wiki paragraph.** Update "Leaving the page mid-cut" in
  `docs/wiki/force-app/recording.md` to match current behaviour (check the 0.1.34 changelog and
  the code); document R1/R3.
- Tests: `npm run test -w force-app-web` (add unit tests for the prefs parser and `newRun`), and
  the web typecheck/build. Use the `force-app-verify` skill if a real UI check is feasible.

## C. Ask-DB — D1, D2

Files: `core/extensions/d1-ask-db/**`, `core/extensions/d1-ask-endpoint/**`,
`plugins/llm-text-to-sql/app/**` and its tests, `plugins/llm-text-to-sql/eval/questions.json`
(read only unless a field is needed), the Ask-DB wiki/runbook page.

- **D1 — Example question chips.** Show 6–8 clickable example questions on the empty chat, drawn
  from the curated gold set (`eval/questions.json`) — bundle a small, hand-picked subset in the
  extension rather than fetching the eval file at runtime, grouped by topic (samples, tests, FAST,
  tooling). Clicking a chip fills and sends the question.
- **D2 — Truncation and errors.** The plugin's API (`row_limit` around `api.py:145-164`) returns
  `row_count` and `truncated` (fetch limit+1 rows to know), the endpoint passes them through, and
  the chat shows "Showing the first N rows" when truncated. Replace raw error strings with clear
  messages for: guard rejection (suggest example questions), model unreachable (502), timeout
  (504), and auth refusal.
- Tests: the plugin's pytest suite (`plugins/llm-text-to-sql/tests`, run locally with a venv if
  Docker is unavailable), the endpoint's tests if any (`node --test` or vitest), and build the
  extension(s) (`npm run build` in each extension folder if they have one).

## D. Directus data entry — X2, D7, D9

Files: one or two new migrations in `db/migrations/`, `core/extensions/d1-lab-dashboard/**`,
`core/extensions/d1-home/src/register-sample.vue`, `core/extensions/d1-sample-code/**`,
`core/extensions/d1-operation-code/**` (only if it has the same max+1 pattern), a new small
endpoint extension if needed (not `d1-ask-endpoint`, which stream C owns),
`docs/wiki/database/known-issues.md` and `roles-and-permissions.md`.

- **X2 — Lab Member can save a cut.** A reversible migration (use the `db-migration` skill)
  modelled on `20260911000111_lab_member_force_analysis_update.sql` that grants the Lab Member
  policy (`20000002-0000-0000-0000-000000000002`) what the Force App's save path needs: create
  (and read, if missing) on `directus_files`, and create on `machining_force_analysis`. Check the
  Force App's upload code (`apps/force-app/web/src` and `backend/app`) for exactly which
  collections and actions it calls, and grant only those. Update `known-issues.md` and
  `roles-and-permissions.md`. Run the `migration-review` skill.
- **D7 — Dashboard click-through.** In `d1-lab-dashboard` detail panels, add "Open in Directus"
  links to the record (`/admin/content/<collection>/<id>`, matching how `d1-home` links) and, for
  samples, a "New operation for this sample" link if a prefill route already exists.
- **D9 — Next sample number.** Replace the fetch-every-`sample_code` (`limit:-1`) max+1 in
  `register-sample.vue` and `SampleCode.vue` with a cheap query: either a Directus aggregate
  (`aggregate[max]` on the sequence column, if one exists) or a small DB function/view exposed
  through an endpoint, so hidden rows are not undercounted. Keep the DB trigger the source of truth;
  the UI only previews.
- Tests: `tests/phase1_schema.sh` or the schema tests if a Postgres is available (the `db-migration`
  skill shows how to prove up/down/up), extension builds, any unit tests next to the extensions.

## Commit trailers

Every commit ends with:

```
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPnGB1Ei8ENvWMdAxmthpu
```
