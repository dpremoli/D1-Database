-- migrate:up
-- Add surrogate UUID PK to sample_stock_provenance for Directus compatibility.
-- Composite uniqueness retained as a UNIQUE constraint.

ALTER TABLE sample_stock_provenance
    DROP CONSTRAINT sample_stock_provenance_pkey;

ALTER TABLE sample_stock_provenance
    ADD COLUMN id UUID NOT NULL DEFAULT uuid_generate_v4();

ALTER TABLE sample_stock_provenance
    ADD CONSTRAINT sample_stock_provenance_pkey PRIMARY KEY (id);

ALTER TABLE sample_stock_provenance
    ADD CONSTRAINT sample_stock_provenance_pair_unique
        UNIQUE (sample_id, lot_id);

-- migrate:down
ALTER TABLE sample_stock_provenance DROP CONSTRAINT sample_stock_provenance_pkey;
ALTER TABLE sample_stock_provenance DROP CONSTRAINT sample_stock_provenance_pair_unique;
ALTER TABLE sample_stock_provenance DROP COLUMN id;
ALTER TABLE sample_stock_provenance
    ADD CONSTRAINT sample_stock_provenance_pkey PRIMARY KEY (sample_id, lot_id);
