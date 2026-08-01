-- migrate:up
-- FRM signal-filtering suite (docs/superpowers/specs/2026-07-21-frm-filtering-suite-design.md):
-- machining_force_analysis.filter_chain holds the op's active chain (JSON: despike/detrend/
-- lowpass/notch stages, fixed order); NULL = no filtering. Baking reprocesses the op with the
-- chain applied at full resolution to every derived output. filter_profiles is the named
-- library — applying a profile COPIES its chain onto the op (no live linkage, so retuning a
-- profile never silently changes other ops' baked outputs).
ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS filter_chain jsonb;

COMMENT ON COLUMN machining_force_analysis.filter_chain IS
    'Active signal-filter chain (despike/detrend/lowpass/notch JSON); NULL = raw. Baked into all derived outputs on reprocess.';

CREATE TABLE IF NOT EXISTS filter_profiles (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL UNIQUE,
    chain       jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE filter_profiles IS 'Named FRM filter-chain library; applying a profile copies its chain onto an operation.';

-- Directus registration (collection hidden from the nav; managed via the dashboard UI).
INSERT INTO directus_collections (collection, icon, note, hidden)
SELECT 'filter_profiles', 'filter_alt', 'Named FRM signal-filter chains', true
WHERE NOT EXISTS (SELECT 1 FROM directus_collections WHERE collection = 'filter_profiles');

INSERT INTO directus_fields (collection, field, interface, display, options, width, sort, readonly, hidden)
SELECT collection, field, interface, display, options::json, width, sort, readonly, hidden
FROM (VALUES
    ('filter_profiles', 'name',  'input',      'raw', NULL, 'half', 1, false, false),
    ('filter_profiles', 'chain', 'input-code', 'raw', '{"language":"json"}', 'full', 2, false, false),
    ('machining_force_analysis', 'filter_chain', 'input-code', 'raw', '{"language":"json"}', 'full', 60, false, false)
) v(collection, field, interface, display, options, width, sort, readonly, hidden)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- migrate:down
DELETE FROM directus_fields WHERE (collection = 'filter_profiles')
    OR (collection = 'machining_force_analysis' AND field = 'filter_chain');
DELETE FROM directus_collections WHERE collection = 'filter_profiles';
DROP TABLE IF EXISTS filter_profiles;
ALTER TABLE machining_force_analysis DROP COLUMN IF EXISTS filter_chain;
