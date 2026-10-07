# ADR-0011 — Row-level visibility: people see the records they are involved in

- **Status:** Accepted (2026-10-07; the owner's decisions are recorded below)
- **Date:** 2026-10-06 (proposed), 2026-10-07 (accepted)
- **Deciders:** Maintainer + Claude (Phase 9 RBAC hardening; Explorer pages track)

## Context

Until this ADR every human account was a **Lab Member** (or Lab Admin). The Lab Member policy in
`scripts/configure_users_and_policies.sql` granted full CRUD on every lab collection with **no
row filter**, so everyone could read and change every sample, operation, test, campaign and
project. ADR-0005 always intended project-level access "as a row-level permission filter, not as
separate roles", deferred to Phase 9 (`plan.md`, "Open / deferred decisions").

The maintainer's target workflow (2026-10-06) is: a user logs in and **sees only the things they
are authorised on** (records they own or co-own), on a clean custom home screen, and browses
projects, campaigns, samples and operations as formatted pages rather than Data Studio forms (see
the [Explorer spec](../superpowers/specs/2026-10-06-explorer-pages-design.md)). The Explorer pages
read through `/items` as the signed-in user, so they show whatever Directus permissions allow.
The restriction itself therefore has to live in the permissions, not in the pages.

The data already records who is involved in a record:

| Record | Involvement columns |
|---|---|
| `projects` | `principal_investigator_person` → `people`; `project_investigators` (M2M alias `secondary_investigators`, `user_id` → `directus_users`). The project form already tells users that investigators "will be recorded as having viewing access to all samples, operations, and test sessions connected to this project" (`scripts/configure_directus.sql`, `investigator_access_notice`). |
| `campaigns` | `owner_person_id` → `people`; `project_id`; the samples in it through `campaign_samples` (alias `samples`) |
| `physical_samples` | `owner_person_id`; `sample_co_owners` (M2M alias `co_owners`, `user_id`); `project_id`; `campaign_samples` (alias `campaigns`) |
| `manufacturing_operations`, `test_sessions` | `owner_person_id` (defaulted to the creator by the `d1-default-owner` hook); `project_id`; `campaign_id`; the sample they act on (`sample_id`) |

`people.user_id` (unique) links a person to their Directus login, so "the current user" in a
filter is `owner_person_id.user_id = $CURRENT_USER`. The older `owner` / `principal_investigator`
UUID columns are hidden backups (`20260703000062_people_directus_meta.sql`) and are not used.

## Owner decisions (2026-10-07)

1. **Rig operators:** there is no technician role. Owners add operators as **co-owners** of the
   samples they work on. A co-owner can read and edit the sample and its operations and tests.
2. **Strict, not focused:** the restriction is enforced by Directus permission filters on the Lab
   Member policy, so the Data Studio and the API are restricted too, not only the Explorer pages.
3. **Ask-DB is unchanged for now.** Its `llm_readonly` Postgres role still reads all lab data.
   This is an accepted, known gap, to be revisited (see "Known gaps"). `d1-ask-endpoint` and the
   LLM role are not touched.
4. **Editing:** update is limited to owners and co-owners, not to PIs and investigators who can
   read a record through the project. Lab Admins are unaffected. Create is open to every member.
   Delete is limited to the owner.

## Decision

### The rules

"Owner" means `owner_person_id` → `people.user_id` equals the signed-in user. "Co-owner" means a
`sample_co_owners.user_id` row for the signed-in user. "PI" means the project's
`principal_investigator_person.user_id`; "investigator" means a `project_investigators.user_id`
row. The machine-readable form of every rule is
[`scripts/access_rules.json`](../../scripts/access_rules.json).

**Read** (a record is visible when any line holds):

| Collection | Visible to |
|---|---|
| `physical_samples` | its owner; a co-owner; the PI or an investigator of its project; the owner of a campaign it belongs to |
| `manufacturing_operations`, `test_sessions` | the record's owner; anyone who can read the sample it acts on (`sample_id`, by the sample rule); the PI or an investigator of its project; the owner of its campaign |
| `campaigns` | its owner; the PI or an investigator of its project; the owner or a co-owner of a sample in it |
| `projects` | the PI; an investigator; the owner of a campaign in it; the owner or a co-owner of a sample in it |
| Child rows (below) | whoever can read the parent row |
| Reference data | every member (unfiltered) |

**Update** (limited to the people who work on the record, so PI and investigator access through
the project is read-only):

| Collection | Updatable by |
|---|---|
| `physical_samples` | its owner or a co-owner |
| `manufacturing_operations`, `test_sessions` | the record's owner, or an owner or co-owner of the sample it acts on (so a co-owned operator can record and fix their own work) |
| `campaigns` | its owner |
| `projects` | its PI |

**Delete:** `physical_samples` by its owner; operations and tests by the record's owner;
campaigns by their owner; projects by their PI.

**Create:** any member, with no filter (Directus does not apply item filters to create). The
`d1-default-owner` hook makes the creator the owner of a new sample, operation, test or
campaign, so the creator can read and edit what they just made.

**Child rows follow the parent.** Read follows the parent's read rule, update and delete follow
the parent's update rule:

| Child collection | Parent it follows |
|---|---|
| `sample_co_owners`, `sample_stock_provenance`, `sample_data_files` | the sample (`sample_id`) |
| `sample_genealogy` | read: either the child or the parent sample; update and delete: the child sample's update rule |
| `campaign_samples` | read: the campaign's or the sample's read rule; update and delete: the campaign's owner or the sample's owner or co-owner |
| `operation_data_files`, `machining_force_analysis`, `fast_run_data` | the operation (`operation_id`); `fast_run_data` has read only and `machining_force_analysis` has no delete, as before |
| `session_data_files`, `test_sessions_subject` | the test (`session_id`, `test_sessions_id`) |
| `project_investigators` | read: the project's read rule; update and delete: the project's PI |
| `project_rollup` (read only) | the project's PI and investigators only |

**Reference data stays readable (and writable, as before) by every member:** `materials`,
`material_iso_classifications`, `alloying_elements`, `material_alloying_elements`, `equipment`,
`manufacturing_methods`, `raw_stock_lots`, `tools`, `tool_boxes`, `cutting_inserts`,
`insert_edges`, `insert_types`, `people`, `facilities`, `fast_recipes`, `force_crawler_state`,
and the `directus_files` create and read grants.

Where a rule says "can read the sample", the *sample* read rule applies in full, so an owner of a
campaign sees the operations and tests on every sample in it.

### The mechanism

Directus **permission filters** on the Lab Member policy (`directus_permissions.permissions`),
using `$CURRENT_USER` and relational paths, for example for `physical_samples` read:

```json
{ "_or": [
  { "owner_person_id": { "user_id": { "_eq": "$CURRENT_USER" } } },
  { "co_owners": { "_some": { "user_id": { "_eq": "$CURRENT_USER" } } } },
  { "project_id": { "principal_investigator_person": { "user_id": { "_eq": "$CURRENT_USER" } } } },
  { "project_id": { "secondary_investigators": { "_some": { "user_id": { "_eq": "$CURRENT_USER" } } } } },
  { "campaigns": { "_some": { "campaign_id": { "owner_person_id": { "user_id": { "_eq": "$CURRENT_USER" } } } } } }
] }
```

The filters are written **once**, in `scripts/access_rules.json`, and turned into rows by
`scripts/gen_access_rules.py`. One migration applies them to the Lab Member policy;
`configure_users_and_policies.sql` carries the same generated rows between markers, because that
script deletes and re-inserts every Lab Member permission on each run and would otherwise remove
the filters. A phase1 test compares the stored permission JSON with the generator's output and a
pytest checks the script block, so neither can drift from the source. A new rule is a change to
the JSON plus a new migration that pastes the regenerated rows.

The rules are documented by intent in `docs/wiki/database/roles-and-permissions.md`, so the
drop-Directus drill (ADR-0002) can re-implement them.

Two schema changes make the filters expressible:

- **`physical_samples.co_owners` was a legacy TEXT column and, at once, the Directus M2M alias
  over `sample_co_owners`.** A filter on `co_owners._some.user_id` is ambiguous with a real column
  of that name. A migration renames the TEXT column to `co_owners_legacy` (when it exists; the
  production snapshot no longer has it).
- **`projects` had no alias for its samples.** The relation `physical_samples.project_id` →
  `projects` gains the hidden alias `samples`, which the project read rule needs for "owns or
  co-owns a sample in it". Directus needs a restart or a cache clear to pick the alias up.

### Paths that bypass Directus permissions, and what each does

| Path | Under this ADR |
|---|---|
| `d1-trace` endpoint | Already correct: SQL functions find ids, then every record is re-read through `ItemsService`. Unreadable relatives show as "N not visible to you" |
| `d1-report` endpoints | Already correct: `ItemsService` checks, then root-knex `v_*` views only for ids shown readable |
| `project_rollup` (cache table read by `d1-project-items`) | Lab Member read is limited to the project's PI and investigators. The Explorer project page reads the real collections instead |
| Ask-DB (`llm_readonly` Postgres role) | **Unchanged: known gap** (below) |
| `directus_files` / `/assets` | Unchanged: known gap (below) |
| Machine users (Operator / Researcher / Administrator roles, `core/roles.json`) | Unchanged: crawler, workers and equipment nodes need everything |

## Known gaps (accepted)

- **Ask-DB.** The `llm_readonly` role (ADR-0009) reads every lab table, so a question typed into
  Ask-DB can return rows the asking user cannot open elsewhere. The owner accepted this for now.
  Revisit by restricting Ask-DB to Lab Admins, or by a scoped mode (the "access table" in
  "Alternatives considered" is the escape hatch). Not changed here.
- **Secondary samples of a multi-sample test.** Tests are matched through the derived primary
  `test_sessions.sample_id` (migration 139: the first sample of the `test_sessions_subject`
  junction). A co-owner of only a *secondary* sample of a test cannot see that test, unless they
  also own it, own its campaign or are PI or investigator of its project. The polymorphic
  `subject` alias cannot be traversed cheaply in a filter.
- **`directus_files` is unchanged.** Any member can read any file, and `/assets/<id>` serves the
  bytes. The Phase 9 export-control item covers it.
- **Create is not filtered.** Directus ignores item filters on create, so a member who can see a
  sample can add themselves to its co-owners, or a junction row to a record they cannot edit.
  Only the owner, the project's PI or a co-owner can then *change or remove* such rows, and the
  `audit_logs` row names who added it. A filter on the payload cannot reach across relations.
- **`audit_logs` read is unchanged.** Lab Members can still read the audit log, which holds the
  old and new values of every change. The log has no owner column to filter on. Restricting it is
  a separate decision.
- **People need a `people` row.** A member without a `people` row linked by `user_id` owns
  nothing, because the hook cannot fill the owner, and sees only what others share with them.
  `people` is not filtered, so a person row can always be created or linked by an admin.
- **Records with no owner.** Legacy rows with a null `owner_person_id` are visible only through
  their project, campaign or co-owners. The migration prints how many exist, so they can be
  assigned before members rely on the filter (`scripts/transfer_sample_ownership.py`).
- **"Belongs to the project".** A sample, operation or test can name its project directly or only
  through its campaign; nothing copies the campaign's project onto it (only the `d1-project-inherit`
  form interface and the campaign pickers do). The read rules use each record's own `project_id`,
  as written above. A PI sees a campaign through its project (campaign rule) but sees the
  campaign's samples only when their own `project_id` is set.

## Alternatives considered

- **A Postgres access table** (`record_access(user_id, …)` kept up to date by triggers, with a
  Directus relation that the filter checks with `_some`). The filters become trivial and the
  same table could scope Ask-DB and a future FastAPI layer (ADR-0002). Rejected for now: it needs
  a trigger on every involvement column, one nullable column per collection (Directus relations
  cannot be polymorphic), and a backfill, before anyone sees a benefit. It stays the escape hatch
  if the filters get slow or Ask-DB needs scoping.
- **Postgres row-level security.** Directus connects as one database user through a pool, so RLS
  would depend on a per-request setting like `d1.actor_identity`, set by the `actor-identity`
  hook. That is fragile across pooled connections and invisible to Directus. Rejected.
- **Per-project roles.** Already rejected in ADR-0005: the number of roles grows with every
  project.
- **A Lab Technician policy that reads all samples** for rig operators. Rejected by the owner
  (decision 1): co-ownership gives the operator exactly the samples they work on.
- **Filter in the UI only** ("my things" by default, everything still readable). Cheap and
  harmless, but not a restriction, so it does not meet "sees only what they are authorised on".

## Consequences

- Lists, counts, dashboards, the Explorer pages, `d1-trace` and `d1-report` all narrow to the
  user's records automatically, because they all read as the user.
- Counts on Home become "yours", not "the lab's". A lab-wide figure would need an admin view or a
  dedicated endpoint.
- Relational filters add subqueries to every Lab Member read. They are fine at lab scale (hundreds
  to thousands of samples). `people.user_id` is unique, and the migration adds the missing indexes
  on the filtered FK and junction columns.
- Operators need to be added as co-owners of a sample before they can record on it. The Force App
  save path creates the operation row as the signed-in user, who becomes its owner, so it keeps
  working; recording on a sample the operator cannot read is not possible, by design.
- Any new collection holding lab data needs a rule in `scripts/access_rules.json` and a migration.
  CONTRIBUTING and the `db-migration` skill say so.
- Live verification needs a real Directus with two test users; it is in
  `docs/runbooks/physical-test-backlog.md`.

## Verification

- `tests/phase1_schema.sh`: the Lab Member permission rows carry exactly the generated filters,
  reference collections stay unfiltered, the script block has not drifted, and the migration
  applies and reverses.
- `tests/scripts/test_access_rules.py`: the generator's output, the script block and the rules'
  invariants (every rule path resolves to real columns and aliases).
- `core/extensions/d1-default-owner/index.test.mjs`: the hook defaults the owner on samples,
  operations, tests and campaigns.
- Physical backlog: as user A (owner) and user B (unrelated), each rule above is visible to A,
  invisible to B, and reachable by B after B is added as a co-owner or investigator.

## References

- ADR-0002 (Directus as a swappable adapter), ADR-0005 (RBAC structure; Phase 9 row filter),
  ADR-0009 (Ask-DB read-only role)
- `scripts/access_rules.json`, `scripts/gen_access_rules.py`, `scripts/configure_users_and_policies.sql`,
  `core/roles.json`
- `db/migrations/20260703000060_people_table.sql`, `20260703000061_people_repoint.sql`,
  `20260703000062_people_directus_meta.sql`, `20260622000029_sample_co_owners.sql`,
  `20260623000030_project_investigators.sql`, `20260710000087_campaign_redesign.sql`,
  `20261007000139_test_sessions_primary_subject_sync.sql`
- `core/extensions/d1-default-owner`, `d1-trace`, `d1-report/src/access.js`
- [Explorer pages spec](../superpowers/specs/2026-10-06-explorer-pages-design.md)
