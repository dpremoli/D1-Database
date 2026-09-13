-- migrate:up
-- Metadata Doctor dismissals. The Doctor (packages/force-plotting/src/metadataDoctor.ts) compares
-- the .mat's own metadata (machining_force_analysis.feed/depth_of_cut/surface_speed/cut_diameter,
-- read out of the file by scripts/matlab/process_force.m) against the D1 operation record, and
-- checks that the derived crop window covers a plausible share of the recording. Some findings are
-- known legacy facts the lab has decided to live with, so they need to be mutable.
--
-- Shape: { "<checkId>": { "sig": "<signature>", "at": "<ISO>", "by": "<user id>" } }, e.g.
--   { "conflict.feed": { "sig": "feed:0.05|0.1", "at": "2026-09-13T…", "by": "…" } }
--
-- `sig` is the point of the design. It is a deterministic signature of the values the finding
-- compared, and a dismissal only suppresses a finding whose recomputed `sig` still matches. If the
-- underlying values later change the dismissal lapses and the finding returns — so muting can never
-- hide a defect that has become real again. That is also why this is not a plain boolean column.
--
-- Two checks need no entry here because they already self-suppress on state the schema carries:
-- crop.coverage on crop_start_idx_override (20260828000103), and conflict.diam on outer_diameter
-- (20260721000096) — in both cases the override IS the human correction.
--
-- No permission migration accompanies this: 20260911000111_lab_member_force_analysis_update.sql
-- already grants Lab Member `update` on this collection with fields='*'.

ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS doctor_dismissed JSONB;

COMMENT ON COLUMN machining_force_analysis.doctor_dismissed IS
    'Metadata Doctor dismissals, keyed by check id: {"<checkId>":{"sig","at","by"}}. A dismissal only suppresses a finding whose recomputed signature still matches, so it lapses when the compared values change.';

-- Registered hidden/readonly: it is written by the plotting UI, never edited by hand in the admin.
INSERT INTO directus_fields (collection, field, interface, display, options, width, sort, readonly, hidden)
SELECT collection, field, interface, display, options::json, width, sort, readonly, hidden
FROM (VALUES
    ('machining_force_analysis', 'doctor_dismissed', 'input-code', 'raw', NULL, 'full', 11, true, true)
) v(collection, field, interface, display, options, width, sort, readonly, hidden)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- migrate:down
DELETE FROM directus_fields WHERE collection = 'machining_force_analysis' AND field = 'doctor_dismissed';
ALTER TABLE machining_force_analysis DROP COLUMN IF EXISTS doctor_dismissed;
