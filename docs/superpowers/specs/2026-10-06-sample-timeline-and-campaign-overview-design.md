# Sample timeline and campaign overview

**Date:** 2026-10-06
**Status:** Implemented (stream M of the 2026-10-06 larger-UX-items batch; UX review rows D5 and D11). Code: `core/extensions/d1-trace/`, `d1-lab-dashboard/src/views/SampleTimeline.vue`, `d1-campaign-ops/src/CampaignOverview.vue` and `overview.js`.
**Scope:** `d1-lab-dashboard` (Sample dashboard), a new `d1-trace` endpoint extension, and
`d1-campaign-ops` (campaign form panel). No schema change.

## Why

- **D5.** Postgres already answers "where did this sample come from and what happened to it"
  (`f_trace_ancestors`, `f_trace_descendants`, `f_trace_stock_origins`, `f_sample_timeline`, in
  `20260619000014_traceability.sql`), but the only way to see the answer was SQL or the report.
  `plan.md` deferred the UI. The Sample dashboard shows operations and tests as two separate lists
  and says nothing about lineage.
- **D11.** `CampaignOps.vue` lists a campaign's operations and nothing else. A campaign's real
  question, "which samples are in it, what has been cut and tested, and has the force data been
  analysed", needs five tabs today.

## D5: options

1. **Browser composes it from `/items` calls.** Permission-safe by construction, but the ancestor
   and descendant walks are recursive, so it is N round trips per generation, and it cannot
   reproduce the cycle guard. Rejected.
2. **Call the functions from the browser** (a Directus flow or a view). The functions are
   `STABLE` SQL run as the database owner, so they ignore Directus permissions and would leak
   samples a role cannot read. Rejected on its own.
3. **Endpoint runs the functions, then filters through Directus permissions.** One round trip,
   one correct recursion, and every record is checked against the caller's role. **Chosen.**

## D5: decision and data flow

A new endpoint extension `d1-trace` (same conventions as `d1-next-number`) mounted at
`GET /d1-trace/sample/:id`.

1. **Auth.** No signed-in user: 401. Signed in without app access (and not admin): 403. `:id` must
   be a UUID: 400.
2. **Root check.** Read the sample through `ItemsService('physical_samples', { schema,
   accountability: req.accountability })`. Not readable or not present: the same 404, so existence
   is not revealed.
3. **Run the four functions** with the shared `database` knex (they bypass permissions, which is
   why step 4 exists). Each list is capped (500 rows) and flagged `truncated` if cut.
4. **Permission filter.** Collect the ids per collection (`physical_samples` from ancestors and
   descendants, `manufacturing_operations` and `test_sessions` from the timeline,
   `raw_stock_lots` from the stock origins) and read each set by primary key through
   `ItemsService.readByQuery` (filter `pk _in ids`) with the caller's accountability. Directus applies the role's item
   filters and field rules, so a record comes back only if the caller can read it. Anything not
   returned is dropped and counted.
5. **Response.** `{ sample, stock_origins, ancestors, events, descendants, hidden: {...counts},
   truncated }`. An ancestor or descendant whose path to the root passes through an unreadable
   sample is kept (the caller can read it) and marked `through_hidden: true`, so the UI can show a
   gap marker instead of implying a direct parent-child link. The path arrays are never sent.

What the functions contribute is limited to identifiers, the sample code, form, relationship type,
fraction, operation pass code and sequence, test type and status, dates, and the lot's code, type,
supplier and mass used. Operator names and file pointers in `f_sample_timeline.detail` are
deliberately not passed on. Readability is decided by the primary-key read; a role whose field
rules hide, say, `sample_code` would still see the code, which we accept for identifier fields.
The relationship edge itself (`sample_genealogy`) is not separately checked: it is shown only
between two samples the caller can read.

**UI.** A "Timeline" tab beside the sample detail on `SampleDashboard.vue` renders: stock lots,
ancestors (oldest first), this sample, its operations and tests by date, then descendants. Every
node is a `router-link` to `/content/<collection>/<id>`. Hidden items collapse into a single
"N items not visible to you" line per section. Loading, empty and error states are explicit; a
latest-request-wins gate drops stale responses.

## D11: options and decision

Schema check (`20260628000047_campaigns.sql`, `20260710000087_campaign_redesign.sql`):

- `manufacturing_operations.campaign_id` and `test_sessions.campaign_id` are direct FKs, so a
  test session can be added to or removed from a campaign by patching `campaign_id`, exactly as
  the existing operations manager does.
- `campaign_samples (campaign_id, sample_id)` is a many-to-many junction, so samples are added by
  creating a junction row and removed by deleting it.
- Force-analysis status lives on `machining_force_analysis` (one row per operation file):
  `status` (`pending|processing|done|error|skipped`, the crawler/orchestrator queue) and
  `diag_status` (`null|pending|processing|done|error`, the Diagnostics build).
- There is **no planned count** on `campaigns` (only `status`, dates and notes), so progress is
  shown as "operations with a completed analysis out of operations", not "done vs. planned".

The panel's data comes from the browser via `useApi` (`/items/...`), so the signed-in user's
permissions apply and no new endpoint is needed. Decision: add an **Overview** section above the
existing operations manager with:

- counts: samples, operations, test sessions, and test sessions by status;
- a per-sample table: code, operations count, tests count, with links to the sample;
- a per-operation list: pass code, sample, force-analysis `status` and `diag_status` badges (with
  the error text on hover), and a progress bar "analysed n / m" (`status = done`) with a second
  count for diagnostics built;
- "Add samples" and "Add test sessions" pickers (search, click to add, remove chips), because
  both links exist in the schema. Testing campaigns primarily use the test-session picker and
  machining trials the operations picker, but all are offered for every type (an imaging campaign
  may have samples only).

Queries use `limit: -1` per campaign, which is bounded by the size of one campaign.

## Out of scope

- A planned-operations count or a progress target (would need a column).
- Filtering the timeline by date or type, or exporting it. The report already prints a sample's
  life.
- Gantt-style visualisation; the first version is a vertical list.
- Changing the Campaign form's native `samples` M2M widget (it stays, hidden or not, as is).
- A project-level overview (P10 covers diagnostics across a campaign separately).
