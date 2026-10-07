# directus-ui-reviewer memory

- 2026-10-07: `physical_samples.co_owners` is a legacy TEXT column and the M2M alias at once; bare `co_owners` reads print ids or the old comma list (caught in E1).
- 2026-10-07: campaign force rows are fetched with a relational filter (`operation_id.campaign_id`), not an `_in` id list; keep it that way (E2).
