-- migrate:up
-- Campaign redesign:
--   1. Add a third campaign type "Imaging / Analysis" (for NDE / imaging work).
--   2. Stop surfacing per-campaign default machine/material — each operation carries
--      its own machine + material, so hide these on the campaign form.
--   3. Samples relate to campaigns MANY-TO-MANY (a sample flows through several
--      campaigns), via a new campaign_samples junction. A project can then show the
--      union of samples across all its campaigns.

-- 1. campaign_type choices
UPDATE directus_fields
   SET options = '{"choices":[{"text":"Machining Trial","value":"machining_trial"},{"text":"Testing Campaign","value":"testing_campaign"},{"text":"Imaging / Analysis","value":"imaging_analysis"}]}'::json
 WHERE collection = 'campaigns' AND field = 'campaign_type';

-- 2. hide default machine/material (each operation has its own)
UPDATE directus_fields SET hidden = true
 WHERE collection = 'campaigns' AND field IN ('default_equipment_id', 'default_material_id');

-- 3. samples <-> campaigns M2M junction
CREATE TABLE campaign_samples (
    id          UUID NOT NULL DEFAULT uuid_generate_v4(),
    campaign_id UUID NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
    sample_id   UUID NOT NULL REFERENCES physical_samples(sample_id) ON DELETE CASCADE,
    CONSTRAINT campaign_samples_pkey   PRIMARY KEY (id),
    CONSTRAINT campaign_samples_unique UNIQUE (campaign_id, sample_id)
);
COMMENT ON TABLE campaign_samples IS 'M2M junction: which physical samples belong to a campaign (a sample may span many campaigns).';
CREATE INDEX campaign_samples_campaign_idx ON campaign_samples (campaign_id);
CREATE INDEX campaign_samples_sample_idx   ON campaign_samples (sample_id);

-- Seed the junction from the existing single campaign_id on each operation's sample,
-- so nothing is lost when moving to M2M (a sample joins every campaign it has an op in).
INSERT INTO campaign_samples (campaign_id, sample_id)
SELECT DISTINCT o.campaign_id, o.sample_id
FROM manufacturing_operations o
WHERE o.campaign_id IS NOT NULL AND o.sample_id IS NOT NULL
ON CONFLICT (campaign_id, sample_id) DO NOTHING;

-- Directus registration (hidden junction collection + M2M fields + relations).
INSERT INTO directus_collections (collection, icon, note, hidden, "group", sort)
VALUES ('campaign_samples', 'link', 'M2M junction: campaign <-> physical sample', true, 'campaigns', 20)
ON CONFLICT (collection) DO NOTHING;

INSERT INTO directus_fields (collection, field, interface, special, width, sort, hidden)
SELECT * FROM (VALUES
    ('campaign_samples', 'campaign_id', 'select-dropdown-m2o', 'm2o', 'half', 1, false),
    ('campaign_samples', 'sample_id',   'select-dropdown-m2o', 'm2o', 'half', 2, false),
    ('campaigns',        'samples',     'list-m2m',            'm2m', 'full', 30, false),
    ('physical_samples', 'campaigns',   'list-m2m',            'm2m', 'full', 60, false)
) v(collection, field, interface, special, width, sort, hidden)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- M2M relations: each junction FK points at its parent, junction_field naming the other FK.
INSERT INTO directus_relations (many_collection, many_field, one_collection, one_field, junction_field, one_deselect_action)
SELECT * FROM (VALUES
    ('campaign_samples', 'campaign_id', 'campaigns',        'samples',   'sample_id',   'delete'),
    ('campaign_samples', 'sample_id',   'physical_samples', 'campaigns', 'campaign_id', 'delete')
) v(many_collection, many_field, one_collection, one_field, junction_field, one_deselect_action)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_relations r
    WHERE r.many_collection = v.many_collection AND r.many_field = v.many_field
);

-- migrate:down
DELETE FROM directus_relations   WHERE many_collection = 'campaign_samples';
DELETE FROM directus_fields      WHERE collection = 'campaign_samples';
DELETE FROM directus_fields      WHERE (collection = 'campaigns' AND field = 'samples') OR (collection = 'physical_samples' AND field = 'campaigns');
DELETE FROM directus_collections WHERE collection = 'campaign_samples';
DROP TABLE IF EXISTS campaign_samples;
UPDATE directus_fields SET hidden = false WHERE collection = 'campaigns' AND field IN ('default_equipment_id', 'default_material_id');
UPDATE directus_fields
   SET options = '{"choices":[{"text":"Machining Trial","value":"machining_trial"},{"text":"Testing Campaign","value":"testing_campaign"}]}'::json
 WHERE collection = 'campaigns' AND field = 'campaign_type';
