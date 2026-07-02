# D1-Database — Directus UI tests

Playwright end-to-end tests that drive the **real Directus admin UI** and assert
the form behaviour the SQL config is supposed to produce. These catch the class
of bug that schema-level checks miss — e.g. a conditional panel that is wired in
`directus_fields.conditions` but doesn't actually toggle in the browser.

## What's covered

| Spec | Asserts |
|------|---------|
| `01-mfg-op-conditional-params` | Manufacturing Operation form: picking a **Process Category** reveals only that type's typed parameter **fields inline** (Machining / Sintering / Additive). |
| `02-test-session-conditional-params` | Test Session form: picking a **Test Type** reveals only that type's typed parameter **fields inline** (Tensile / Hardness). |
| `03-sample-geometry-preview` | Physical Sample form: the custom **Shape Preview** interface draws a live SVG from Geometry + dimensions. |
| `04-project-investigators` | Project form: the **Secondary Investigators** M2M field and its access-notice are present. |
| `05-detail-pages-load` | Regression: opening an **existing** record (samples/projects/operations/sessions) returns the form, not a 500 / "Page Not Found". Catches alias fields missing `no-data` and M2M junctions whose tables don't exist. |
| `10-ask-db-chat` | **Ask the Database** module: a stubbed proxy response renders the SQL block, result table, and Plotly chart; the `/d1-ask/chat` endpoint rejects unauthenticated requests (401) and passes the auth gate for a logged-in session. A live end-to-end smoke runs only with `D1_LLM_LIVE=1`. |

## Prerequisites

- The full stack is up (`docker compose up -d`) and Directus is reachable at
  `http://localhost:8055`.
- `scripts/configure_directus.sql` has been applied and Directus restarted
  (after a Redis flush) so the latest field config is served.

## Run

```bash
cd tests/ui
npm install                  # first time only
npx playwright install chromium   # first time only
npx playwright test          # run everything
npx playwright test 01-mfg   # run one spec
npx playwright show-report report   # open the HTML report
```

### Config / credentials

Overridable via env vars (defaults in parentheses):

- `D1_BASE_URL` (`http://localhost:8055`)
- `D1_ADMIN_EMAIL` (`admin@example.com`)
- `D1_ADMIN_PASSWORD` (`change_me_admin`)

Each test logs in fresh via the `fixtures.ts` `page` fixture. We deliberately do
**not** share one stored session: Directus rotates refresh tokens, so a session
shared across browser contexts gets invalidated when the first context refreshes
it (which silently logged out later tests and made the suite flaky).

## Notes

- Typed parameters are **inline columns** on `test_sessions` /
  `manufacturing_operations` (prefixed per type, e.g. `hardness_load_gf`),
  conditionally shown by the scalar discriminator (`test_type` /
  `process_category`). They were flattened out of the old per-type param tables
  by `db/migrations/20260623000032_inline_param_fields.sql` +
  `scripts/flatten_param_fields.py`. Directus field conditions do **not**
  evaluate against the `method_id` M2O relation — hence the scalar
  `process_category` (migration 031).
- Run order after a config change: `configure_directus.sql` **then**
  `scripts/configure_inline_params.sql` (the latter registers the inline fields
  and is idempotent).
- After changing `configure_directus.sql`, always flush Redis
  (`docker exec d1-database-redis-1 redis-cli FLUSHALL`) and restart Directus
  before re-running, or the UI serves stale field metadata.
- `report/`, `test-results/`, `.auth/`, and `node_modules/` are git-ignored.
