# directus-ui-reviewer memory

- 2026-10-07: `physical_samples.co_owners` is a legacy TEXT column and the M2M alias at once; bare `co_owners` reads print ids or the old comma list (caught in E1).
- 2026-10-07: campaign force rows are fetched with a relational filter (`operation_id.campaign_id`), not an `_in` id list; keep it that way (E2).
- 2026-10-07: bug class: "try the full filter, catch everything, retry narrower" (E3 useMyWork.withFallback) turns network/500 errors into a false "you cannot read X" note. Gate fallbacks on `isForbidden` (E2 `campaign/errors.ts`).
- 2026-10-07: bug class: capped reads (`limit: 5000`) that feed computed counts or progress bars with no truncation flag undercount silently. Check every `*_CAP` consumer for a `length >= cap` flag (E3 PROGRESS_ROW_CAP).
- 2026-10-07: not a finding: Lab Member reads `people` with fields '*' (migration 066), so `principal_investigator_person.user_id` / `owner_person_id.user_id` in fields or filters is safe today. `manufacturing_operations.force_analyses` is a real O2M alias (migration 075).
- 2026-10-07: not a finding: activity.ts ISO-week binning passes its tests under TZ=Europe/London, America/Los_Angeles and Pacific/Auckland. Re-run that loop only if activity.ts changes.
- 2026-10-07: not a finding: Directus 11 `userStore.isAdmin` is a boolean getter fed by `admin_access` from /policies/me/globals; `role.admin_access` is v10 only. Treat `isAdmin ?? admin_access` as fine.
- 2026-10-07: hotspot: E2 and E3 both edit the route table in `d1-home/src/index.ts`, the export tail of `packages/d1-ui/src/index.ts` and the tail of `physical-test-backlog.md`, so they merge-conflict there. Campaign type labels and test "done" statuses belong in `d1-ui/src/campaign/{campaignType,rollup}.ts`; flag local copies.
- 2026-10-07: schema quirk: Directus offers campaign_type `imaging_analysis`, but the DB CHECK (migration 047) still allows only machining_trial/testing_campaign. Pages must not assume "not testing means machining".
