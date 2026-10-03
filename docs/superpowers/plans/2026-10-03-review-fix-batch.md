# Review fix batch — 2026-10-03

Fixes for the findings in [`docs/reviews/2026-10-03-general-code-review.md`](../../reviews/2026-10-03-general-code-review.md).
Finding ids like **1.3** mean stream 1, finding 3, in the raw reports under
`docs/reviews/2026-10-03-general-code-review/stream-<n>-*.md`; each gives `file:line`, the
scenario and a suggested fix. Delete this plan, and `2026-10-03-general-code-review.md`, once the
batch has shipped (see `docs/superpowers/README.md`).

## 1. Decisions taken for this batch

The owner asked for the batch to go ahead. Where the review listed an owner decision, this batch
takes the conservative, reversible option below; each one can be widened later.

| Question | Taken here |
|---|---|
| Who may use `/d1-ask` (4.2) | Admins and users with app access (`accountability.app`). API-only tokens such as Rig_1 get 403. |
| Who may use `/d1-report` (4.1) | Whoever can read the base row under their own Directus permissions (read through `ItemsService` with the caller's accountability). No policy change. |
| Text-to-SQL table access (5.8, 6.4) | Explicit allow-list of lab tables and views for `d1_llm_readonly`; no default-privileges auto-grant; `audit_logs`, `people`, `Machine_Operators` and every `directus_*` table excluded. This restores ADR-0009's original rule. |
| Audit coverage (5.3) | Every business table gets the audit trigger, as ADR-0003 already says. Cascade rules on sample delete are unchanged. |

## 2. Held back (not in this batch)

| Item | Why |
|---|---|
| 4.3 `apply.sh` / `permissions.json` vs Directus v11 policies | Port or retire is an owner decision; needs a live v11 stack to test. |
| `UNIQUE(pass_code)`, `UNIQUE(sample_id, operation_sequence)` (4.5) | Production may already hold duplicates; needs a data check first. This batch makes assignment server-side and race-free instead. |
| 5.5, 5.6 lossy down sections | Applied migrations can't be edited; documented, not changed. |
| 5.9, 5.10, convention counts (602 uncommented columns, 65 unindexed FKs) | Large, mechanical, low risk; a separate hygiene pass. |
| 6.11 plugin contract drift beyond the webhook 400 | Doc rewrite; separate pass. |
| 1.6 on Windows, 2.9, the sidecar parent-death watchdog | Logic fixed and unit-tested here; behaviour needs the Windows rig. |
| 7.13, 7.15–7.18 nits, 3.12–3.14 | Low impact; revisit with the hygiene pass. |

## 3. Work streams

Each stream owns its files, so streams can run in parallel. Migration version slots are fixed
per stream so numbers never collide: **B** `20261003000117`, **C** `20261003000118`–`…000125`,
**I** `20261003000126`–`…000129`.

### A. Compose, env, infra, CI — 6.1 6.2 6.9 6.10 7.8 (P0 security)
Files: `docker-compose.yml`, `.env.example`, `infra/`, `Makefile`, `.github/workflows/`,
`docs/plugin-contract.md` (§2.3 only), `docs/runbooks/` where they describe these.
- Host ports bound to `127.0.0.1` by default (override via env for tailnet IP); Redis not
  published, `requirepass` + password in every `REDIS_URL`.
- Secrets use `${VAR:?}` in compose; `.env.example` placeholders that cannot work as-is.
- Postgres healthcheck `$$POSTGRES_USER`; drop the unused `archive_share` mounts on the workers.
- `backup.sh` writes `.tmp`, `gzip -t`, renames; `restore.sh` verifies the file, typed-name
  confirmation, `psql -v ON_ERROR_STOP=1 --single-transaction`; prune keeps the last N.
- Makefile loads `.env`; `reset-db` asks for typed confirmation.
- `EMBED_DATABASE_URL` uses a non-superuser role (document the grant).
- Workflows: top-level `permissions: contents: read`; release job `persist-credentials: false`
  and `contents: write` only on the publishing step/job; pwsh steps fail on each native command
  (`$ErrorActionPreference='Stop'` + `$PSNativeCommandUseErrorActionPreference = $true`).
- Tests: `bash tests/phase0_smoke.sh`, `docker compose config -q` (with and without a test
  `.env`), `bash -n`, actionlint/yamllint if available.

### B. Text-to-SQL, `/d1-ask`, `/d1-report` — 4.1 4.2 6.4 5.8 (P0 security)
Files: `plugins/llm-text-to-sql/`, `core/extensions/d1-ask-endpoint/`,
`core/extensions/d1-report/`, migration `20261003000117_llm_readonly_allow_list.sql`,
`tests/phase6_text_to_sql.sh`, `docs/adr/0009-*` (status note only).
- `d1-report`: read via `ItemsService` with the caller's accountability; 403/404 identical for
  "not found" and "not permitted".
- `d1-ask`: role gate per §1; forward only `messages` (count and length capped); `AbortSignal`
  timeout; 503 when `WORKER_WEBHOOK_SECRET` is unset.
- `sql_guard`: CTE names resolved per scope; function allow-list (reject `query_to_xml`,
  `*_to_xml`, `pg_read_*`, `set_config`, `pg_sleep`, `dblink*`, `lo_*`); reject `FOR UPDATE/SHARE`
  and functions in FROM unless allow-listed; `row_limit`/`limit` clamped.
- Migration: revoke all, grant an explicit list, drop the default-privileges grant; create
  `d1_llm_app` (NOLOGIN in the migration; password set by the runbook) with `default_transaction_read_only`.
- Tests: guard bypass cases from 6.4 as unit tests; phase6 asserts "permission denied" text and
  checks `has_table_privilege` for writes; the plugin's pytest.

### C. Schema integrity — 5.1 5.2 5.3 5.4 5.7 4.7 4.8 (P0 data + P1)
Files: migrations `20261003000118`–`…000125`, `tests/phase1_schema.sh` (and a new
`tests/phase1_catalog.sh` if cleaner), `core/extensions/owner-cascade/`,
`core/extensions/box-intake/`, `scripts/configure_*.sql` only where a moved rule needs it.
- 5.1: `refresh_project_rollup()` takes `pg_advisory_xact_lock` first (and stays correct under
  concurrency); test with two concurrent sessions.
- 5.2: LEFT JOIN `physical_samples` in `v_manufacturing_operations_full` and
  `v_test_sessions_full`; row-parity test.
- 5.3: audit trigger on every business table; `record_id` from the table's real PK (via
  `TG_ARGV` or a `pg_index` lookup).
- 5.4: OCC triggers on tables that have `version`.
- 5.7: `audit_trigger_function` `SET search_path = pg_catalog, public`, qualified names;
  `REVOKE TRUNCATE` on `audit_logs` from non-owners plus an `ON TRUNCATE` guard trigger.
- 4.7: owner cascade and box intake move to Postgres triggers (one transaction, errors reach the
  user); the Directus hooks become no-ops or are removed, per ADR-0002.
- 4.8: `expand_tool_box_intake` copies `owner_person_id`; base sequence from `max(code)+1` under
  an advisory lock instead of `COUNT(*)`.
- Every migration reversible; prove up → down → up on local Postgres 16 (`db-migration` skill);
  run `migration-review` before handing back.

### D. force-app backend, backup server, relay — 1.1–1.11 (P0 data + security)
Files: `apps/force-app/backend/`, `apps/force-app/backup-server/`,
`apps/force-app/bug-report-relay/`.
- 1.1 `_consume` try/except records the error and stops; `Ring.close()` never blocks.
- 1.2 formula arity validation; any evaluation exception becomes `FormulaError`.
- 1.3 `127.0.0.1` in `start_recorder.ps1` and the Doctor fix text.
- 1.4 `_busy()` guard on the NI-DAQ tacho/card/channel endpoints, with a test.
- 1.5 re-check `_busy()` with no await before assigning `_session`.
- 1.6 `is_safe_id` and backup `_session_dir` reject `:` and anything that isn't its own basename.
- 1.7 Origin/Host middleware (HTTP and WS handshake); keep the desktop `app://force` origin and
  the dev origins working.
- 1.8 replay > 600 s; 1.9 duplicate `/ingest/start` keeps data; 1.10 `calendar.timegm` + 401
  retry; 1.11 ruff; plus the stream-1 nits that are one-liners.
- Tests: a test per fix; `ruff check`, `pytest` in each of the three services.

### E. force-app web and desktop — 2.1–2.11
Files: `apps/force-app/web/`, `apps/force-app/desktop/`.
- 2.1 reconcile from `/record/status` on mount and on every WS (re)open; WS reconnect with
  backoff; `client.stop()` throws on non-ok and the UI shows it.
- 2.2 save retry resumes from the stored op id and uploaded files (and `uploadCapture.ts`).
- 2.3 + 2.4 `finalizing` counts as busy in the quit guard and updater; the update dialog
  re-checks before installing.
- 2.5 `busy` set before pre-flight; 2.6 polling restarts on remount; 2.7 request tokens in
  `searchCuts` / `pickReplayCut`; 2.8 Connectivity Save/Reset; 2.9 race startup wait against
  exit; 2.10 IPC listener disposers; 2.11 `will-navigate` deny + `fromApp` on `update:*`; the
  stream-2 nits.
- Tests: unit tests for each; `npm test` + `typecheck` for both workspaces, `lint:theme`.

### F. force-plotting — 3.1–3.11
Files: `packages/force-plotting/`, `core/extensions/d1-force-dashboard/` (host wiring only).
- 3.1 guard every async write to `detail.value` by op id; polling loops cancel on op change and
  unmount.
- 3.2 + 3.3 FrmCloud reactivate (fresh canvas or no forced context loss; zero `raf`/`cropTimer`).
- 3.4 hover index under zoom; 3.5 debounce + abort spectrogram fetches; 3.6 FrmOctree
  deactivate; 3.7 listener removal; 3.8 load token; 3.9 polar sign handling; 3.10 rho-only
  path for crop drags; 3.11 stale guard and `??`.
- Tests: unit tests for each pure fix, lifecycle tests where feasible; `npm test` + `typecheck`.

### G. Scripts and script tests — 7.1–7.12, 7.14
Files: `scripts/` (not `scripts/configure_*.sql` beyond 7.10's transaction wrapping),
`tests/scripts/`, `tests/phase3_api.sh`, `tests/phase4_heavy_data.sh`,
`tests/phase7_traceability.sh`, `tests/ui/`, `tests/README.md`.
- 7.1 index_archive move re-points every FK to `directus_files` (query the catalog) and never
  deletes a referenced row; collision check.
- 7.2 clear_fast_logs refuses to clobber a non-empty backup, requires `--yes`; 7.9 dry-run on
  revert; 7.10 `ON_ERROR_STOP` + transactions in `configure_all.sh`.
- 7.3–7.7 test-script and legacy-migration fixes; 7.11 assertions that can fail and pass for the
  right reason; 7.12 deterministic KD-tree tie-break (regenerate goldens only if the tie-break
  changes them, and say so); 7.14 `sos` filters.
- Tests: `pytest tests/scripts` (all green), `ruff`, `bash -n`.

### H. Compute plugins — 6.3 6.5 6.6 6.7 6.8 (+ the stream-6 id-validation nits)
Files: `plugins/analysis-worker/`, `plugins/heavy-data-worker/`, `plugins/filter-service/`,
`plugins/diag-service/`, `plugins/plugin-template/`.
- `check_secret` fails closed when the secret is unset (all workers + template).
- 6.3 contiguous-block Welch PSD (or proper decimation), effective Nyquist reported; window
  function; distinct peaks.
- 6.5 `job_timeout`, a reaper for stale `processing`, `wait -n` in `entrypoint.sh`.
- 6.6 OCC version filter on write-back; abort on read failure.
- 6.7 cache keys include mtime/size; 6.8 sync handlers off the event loop, cap `despike.window`.
- Validate ids as UUIDs before building Directus URLs.
- Tests per fix; `pytest` in each plugin; `ruff check plugins`.

### I. Directus extensions — 4.5 4.6 4.9 4.10 4.11 4.12
Files: `core/extensions/` except those owned by B and C; migrations `…000126`–`…000129`.
- 4.5 + 4.6 sequence and code assignment server-side (BEFORE INSERT trigger or function under an
  advisory lock); the interfaces show a preview but the database decides.
- 4.9 confirm or fix actor identity; test asserting `actor_identity` is set.
- 4.10 request sequencing, `catch`, cleanup on unmount; Crawler fixes.
- 4.11 the category comes from Postgres; the interface never blanks a stored value.
- 4.12 Operator can't set `export_controlled`; prep-recipe op-type check.
- Tests: extension builds; schema tests for the new triggers.

## 4. Status

Update when a stream changes state (see "Resuming interrupted work" in `CLAUDE.md`). Workers run
on Sonnet, three or four at a time, each in `.claude/worktrees/agent-<id>` on branch
`worktree-agent-<id>` (stream A: `.claude/worktrees/stream-a`, branch `worktree-stream-a`), based on
`80e52bd`. The harness created the wave-1 worktrees on a stale base (`73a8547`); they were
moved to `80e52bd` before any work. Check each worktree's base before launching later waves. The coordinator reviews and merges
each stream into `ccr-c5556a5a-jxwm8s`.

| Stream | Wave | Worktree / branch id | State |
|---|---|---|---|
| A | 1 | `stream-a` (branch `worktree-stream-a`) | done (`266c2f7`..`e682f82`), reviewed; merge together with H (Redis URL) |
| B | 1 | `agent-a87e02935fb18bd77` | in progress |
| D | 1 | `agent-a919838a2c96882aa` | in progress |
| H | 1 | `agent-a9501193950e18778` | in progress |
| C | 2 | — | pending |
| E | 2 | — | pending |
| F | 2 | — | pending |
| G | 2 | — | pending |
| I | 3 | — | pending |

## 5. After the streams merge

1. Merge every stream into `ccr-c5556a5a-jxwm8s` and resolve conflicts.
2. Review the whole diff (correctness first) and fix the findings.
3. Run every suite: backend, backup-server and relay pytest; web, desktop and plotting vitest
   and typecheck; plugin pytest; `tests/scripts`; schema tests and up/down/up on local Postgres.
4. Changelog entry and desktop version bump (0.1.34) for the force-app changes.
5. Open the PR.
