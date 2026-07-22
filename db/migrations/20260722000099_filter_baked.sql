-- migrate:up
-- Distinguishes a LIGHT filter apply from a full bake. When a user "keeps" a filtered version
-- as the op's default (docs/superpowers/specs/2026-07-21-frm-filtering-suite-design.md), we save
-- machining_force_analysis.filter_chain WITHOUT reprocessing (status stays 'done'): the Lite cloud
-- recomputes the chain live from the raw cache, but the Full octree / FRM PNGs stay raw until an
-- explicit "Bake to outputs" reprocess (or the crawler rebuilds). filter_baked=true means every
-- derived output has actually been reprocessed with the chain, so the UI can label them honestly
-- ("filtered" everywhere) versus "filtered · Lite" for a light apply.
ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS filter_baked boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN machining_force_analysis.filter_baked IS
    'True once every derived output (Lite cache, Full octree, FRM PNGs) has been reprocessed with filter_chain. False = light apply (chain saved; Lite recomputes live; other outputs still raw).';

INSERT INTO directus_fields (collection, field, interface, display, options, width, sort, readonly, hidden)
SELECT 'machining_force_analysis', 'filter_baked', 'boolean', 'boolean', NULL, 'half', 61, false, true
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = 'machining_force_analysis' AND f.field = 'filter_baked'
);

-- migrate:down
DELETE FROM directus_fields WHERE collection = 'machining_force_analysis' AND field = 'filter_baked';
ALTER TABLE machining_force_analysis DROP COLUMN IF EXISTS filter_baked;
