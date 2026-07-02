-- migrate:up
-- 1. Add surrogate UUID PK to material_alloying_elements so Directus can manage
--    it as a junction collection (Directus ignores tables with composite PKs).
ALTER TABLE material_alloying_elements
    ADD COLUMN id UUID NOT NULL DEFAULT uuid_generate_v4();

ALTER TABLE material_alloying_elements
    DROP CONSTRAINT material_alloying_elements_pkey;

ALTER TABLE material_alloying_elements
    ADD CONSTRAINT material_alloying_elements_natural_key UNIQUE (material_id, symbol),
    ADD PRIMARY KEY (id);

-- 2. Convert owner TEXT → UUID on all domain tables so owner fields can link
--    to directus_users via Directus M2O config (no hard DB FK keeps Directus
--    swappable per ADR-0002).
--    Existing AppSheet text names are cleared — re-assign via the new picker.
UPDATE tool_boxes      SET owner = NULL;
UPDATE cutting_inserts SET owner = NULL;
UPDATE physical_samples SET owner = NULL;

ALTER TABLE tool_boxes
    ALTER COLUMN owner TYPE UUID USING owner::UUID;

ALTER TABLE cutting_inserts
    ALTER COLUMN owner TYPE UUID USING owner::UUID;

ALTER TABLE physical_samples
    ALTER COLUMN owner TYPE UUID USING owner::UUID;

-- 3. Add owner to insert_edges (box → inserts → edges cascade path)
ALTER TABLE insert_edges
    ADD COLUMN IF NOT EXISTS owner UUID;

-- 4. Cascade-ownership flag on tool_boxes and cutting_inserts.
--    When TRUE on save, the owner-cascade Directus hook propagates the current
--    owner value to all child records, then resets this flag to FALSE.
ALTER TABLE tool_boxes
    ADD COLUMN IF NOT EXISTS cascade_ownership BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE cutting_inserts
    ADD COLUMN IF NOT EXISTS cascade_ownership BOOLEAN NOT NULL DEFAULT FALSE;

-- migrate:down
ALTER TABLE tool_boxes
    DROP COLUMN IF EXISTS cascade_ownership,
    ALTER COLUMN owner TYPE TEXT USING NULL;

ALTER TABLE cutting_inserts
    DROP COLUMN IF EXISTS cascade_ownership,
    ALTER COLUMN owner TYPE TEXT USING NULL;

ALTER TABLE physical_samples
    ALTER COLUMN owner TYPE TEXT USING NULL;

ALTER TABLE insert_edges
    DROP COLUMN IF EXISTS owner;

ALTER TABLE material_alloying_elements
    DROP CONSTRAINT IF EXISTS material_alloying_elements_natural_key,
    DROP COLUMN IF EXISTS id;

-- Restore composite PK (approximate — original constraint name may differ)
ALTER TABLE material_alloying_elements
    ADD PRIMARY KEY (material_id, symbol);
