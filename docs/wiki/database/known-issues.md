# Known issues

[← D1 Database wiki](README.md)

Problems found while building a fresh stack from the repository and writing this wiki
(September 2026). Each was reproduced on that stack. Production may differ where it was changed
by hand in the Directus UI.

## Fixed alongside this wiki

| Issue | Fix |
|---|---|
| The Directus **module bar was empty** on a freshly configured database: `configure_directus.sql` wrote the entries without `"enabled": true`, which Directus requires | the script now writes enabled entries, including Force Analysis and FAST Analysis, and repairs a bar written by the old version |
| **Lab Dashboard → Samples** showed no operations and no test sessions for any sample: it sorted test sessions by `test_date`, which does not exist (the column is `session_date`), and the failed request took the operations list down with it | the query and the date display use `session_date` |
| **Force App: the live FFT / Power panel stayed blank** until a channel chip was clicked | `LiveFft.vue` now tracks spectrum updates |

## Open

| Issue | Effect | Workaround |
|---|---|---|
| **Lab Dashboard Node Graph** requests `manufacturing_operations.operation_type`, which does not exist | expanding a sample, machine or edge in the connection graph returns nothing (403 in the browser console) | use the record's own related lists |
| **Lab Member has no `directus_files` access** and cannot create `machining_force_analysis` rows | a Lab Member cannot save a cut from the Force App (the operation row is created, then the upload fails), and cannot open live caches in Force Analysis | record as a Lab Admin. Grant the permissions in a migration. See [Roles](roles-and-permissions.md#what-lab-member-cannot-do-as-configured-in-the-repository). |
| **Force App cuts are never host-processed**: the orchestrator only handles `.mat` files indexed from the archive | no stored FFT, FRM *Figure*, *Full* octree or diagnostics for cuts saved from the app | copy the capture into the archive and index it. See [Force data](force-data.md#two-ways-in). |
| **Force App: "upload state unknown"** on every local capture: the check filters on `recorded_metadata.capture_id`, a key inside a JSON field, which Directus refuses | the per-capture **Upload** buttons never appear | upload from the save dialog, or store the capture id in a real column |
| **Migrations 057 and 066 fail on a fresh real Directus database** (foreign keys to rows that the configure scripts create later) | a from-scratch rebuild stops part-way | see the [developer guide](developer-guide.md#problems-you-will-hit) |
| **`configure_directus.sql` removes migration-added metadata** for the core collections | re-applying it loses about a hundred field interfaces and relations; `fast_recipes` then errors | see the [developer guide](developer-guide.md#problems-you-will-hit) |
| **Two extension lock files are stale** (`d1-material-inherit`, `d1-report`) | `npm ci` fails with `EUSAGE` | `npm install` and commit the lock file |
| **Seeded machines have no capabilities** (`db/seeds/001_reference_data.sql`) | on a dev stack the machine picker offers none of them | set `equipment.capabilities` |
