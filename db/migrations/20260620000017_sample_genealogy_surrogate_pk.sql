-- migrate:up
-- Directus requires a single-column primary key.
-- Replace the composite PK (child_sample_id, parent_sample_id) with a
-- surrogate UUID, retaining the pair uniqueness as a UNIQUE constraint.

ALTER TABLE sample_genealogy
    DROP CONSTRAINT sample_genealogy_pkey;

ALTER TABLE sample_genealogy
    ADD COLUMN id UUID NOT NULL DEFAULT uuid_generate_v4();

ALTER TABLE sample_genealogy
    ADD CONSTRAINT sample_genealogy_pkey PRIMARY KEY (id);

ALTER TABLE sample_genealogy
    ADD CONSTRAINT sample_genealogy_pair_unique
        UNIQUE (child_sample_id, parent_sample_id);

-- migrate:down
ALTER TABLE sample_genealogy DROP CONSTRAINT sample_genealogy_pkey;
ALTER TABLE sample_genealogy DROP CONSTRAINT sample_genealogy_pair_unique;
ALTER TABLE sample_genealogy DROP COLUMN id;
ALTER TABLE sample_genealogy
    ADD CONSTRAINT sample_genealogy_pkey PRIMARY KEY (child_sample_id, parent_sample_id);
