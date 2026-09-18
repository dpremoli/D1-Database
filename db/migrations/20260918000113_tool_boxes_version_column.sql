-- migrate:up
-- tool_boxes is missing the `version` OCC column that every other mutable
-- table in the tooling hierarchy carries (cutting_inserts, insert_edges,
-- insert_types all have it — see docs/data-dictionary.md "OCC concurrency
-- pattern": "All mutable tables carry `version INTEGER` and `updated_at
-- TIMESTAMPTZ`"). The 20260618000010_occ_triggers.sql migration already
-- attaches a BEFORE UPDATE trigger (occ_tool_boxes) to this table that reads
-- and writes NEW.version, but the column itself was never present on the
-- live table, so any UPDATE on tool_boxes raises:
--   "record "new" has no field "version""
-- This silently aborts expand_tool_box_intake() before it can create the
-- box's cutting_inserts/insert_edges, so adding a new insert box never
-- generated its children.
ALTER TABLE tool_boxes
    ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

-- migrate:down
ALTER TABLE tool_boxes DROP COLUMN IF EXISTS version;
