# General code review — 2026-10-03

A whole-repo review (not a diff review) of `main` at `8dbb529`, run on branch
`ccr-c5556a5a-jxwm8s`. Each stream is a read-only Sonnet reviewer that owns one area, runs that
area's cheap checks, and reports ranked findings with `file:line`. The coordinator verifies the
findings and writes the consolidated report to
[`docs/reviews/2026-10-03-general-code-review.md`](../../reviews/2026-10-03-general-code-review.md).
No code is changed in this pass; fixes go in a follow-up batch once the owner has picked which
findings to act on. Delete this plan once that follow-up has shipped.

## Streams

| Stream | Area (files owned) | Checks to run |
|---|---|---|
| 1 | `apps/force-app/backend`, `apps/force-app/backup-server`, `apps/force-app/bug-report-relay` | `ruff check`, `pytest -q` in each |
| 2 | `apps/force-app/web`, `apps/force-app/desktop` | `npm test` / `typecheck` for those workspaces |
| 3 | `packages/force-plotting` | `npm test` / `typecheck` for the workspace |
| 4 | `core/` (Directus extensions, `apply.sh`, roles/permissions) | build/typecheck where cheap |
| 5 | `db/` (migrations, seeds), `tests/phase*_*.sh` | static review against the migration rules |
| 6 | `plugins/`, `infra/`, `.github/`, `docker-compose.yml`, `Makefile`, `.env.example` | `pytest -q` per plugin, `ruff check` |
| 7 | `scripts/` (incl. `scripts/diag`, `scripts/matlab`), `tests/scripts`, `tests/ui` | `pytest -q tests/scripts` |

## Status

Update when a stream changes state (see "Resuming interrupted work" in `CLAUDE.md`). Reviewers
are read-only, so there are no worktrees; a stopped stream is simply relaunched with its row's
brief.

| Stream | Agent | State |
|---|---|---|
| 1 | Sonnet reviewer | done; blockers 1 and 3 verified |
| 2 | Sonnet reviewer | done; raw report in `docs/reviews/2026-10-03-general-code-review/`; blockers 1 and 3 verified |
| 3 | Sonnet reviewer | done; blocker 1 and hover finding 4 verified |
| 4 | Sonnet reviewer | done; blockers 1 and 2 verified |
| 5 | Sonnet reviewer | done; blocker 1 and view finding 2 verified |
| 6 | Sonnet reviewer | in progress |
| 7 | Sonnet reviewer | in progress |
| Consolidated report | coordinator | pending |
