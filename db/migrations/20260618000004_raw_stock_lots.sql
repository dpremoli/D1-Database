-- migrate:up
-- Raw stock ledger: tracks inbound material before any manufacturing step.
-- Currently absent from the AppSheet data (provenance is free-text on FAST Runs).
-- This is a genuinely new entity — see docs/legacy-data-analysis.md §5.

CREATE TABLE raw_stock_lots (
    lot_id                      UUID            NOT NULL DEFAULT uuid_generate_v4(),
    lot_code                    VARCHAR(64)     NOT NULL,
    stock_type                  TEXT            NOT NULL,
    material_id                 UUID,
    supplier_name               TEXT,
    supplier_part_number        TEXT,
    mesh_size_micrometres       NUMERIC(10, 3),
    purity_percent              NUMERIC(7, 4),
    inbound_mass_grams          NUMERIC(12, 4)  NOT NULL,
    remaining_mass_grams        NUMERIC(12, 4)  NOT NULL,
    received_date               DATE,
    certificate_url             TEXT,
    export_controlled           BOOLEAN         NOT NULL DEFAULT FALSE,
    notes                       TEXT,
    created_at                  TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ     NOT NULL DEFAULT now(),
    version                     INTEGER         NOT NULL DEFAULT 1,
    CONSTRAINT raw_stock_lots_pkey PRIMARY KEY (lot_id),
    CONSTRAINT raw_stock_lots_code_unique UNIQUE (lot_code),
    CONSTRAINT raw_stock_lots_material_id_fkey
        FOREIGN KEY (material_id)
        REFERENCES materials (material_id),
    CONSTRAINT raw_stock_lots_stock_type_check
        CHECK (stock_type IN ('swarf', 'powder', 'billet', 'chemical', 'other')),
    CONSTRAINT raw_stock_lots_remaining_mass_check
        CHECK (remaining_mass_grams >= 0),
    CONSTRAINT raw_stock_lots_inbound_mass_check
        CHECK (inbound_mass_grams > 0)
);

COMMENT ON TABLE raw_stock_lots
    IS 'Inbound material ledger. Every manufactured sample must trace back to one or more'
       ' lots here to maintain material provenance (the weakest link in the legacy data).';
COMMENT ON COLUMN raw_stock_lots.lot_code
    IS 'Human-readable lot identifier, unique across all stock.';
COMMENT ON COLUMN raw_stock_lots.stock_type
    IS 'Form of the raw stock: swarf, powder, billet, chemical, or other.';
COMMENT ON COLUMN raw_stock_lots.mesh_size_micrometres
    IS 'Powder mesh/particle size in micrometres. NULL for non-powder stock.';
COMMENT ON COLUMN raw_stock_lots.purity_percent
    IS 'Material purity as a percentage (0–100). NULL for alloys/billets.';
COMMENT ON COLUMN raw_stock_lots.inbound_mass_grams
    IS 'Total mass received in grams. Must be > 0.';
COMMENT ON COLUMN raw_stock_lots.remaining_mass_grams
    IS 'Current remaining mass in grams. Decremented as material is consumed.';
COMMENT ON COLUMN raw_stock_lots.certificate_url
    IS 'URI to material certificate or datasheet in MinIO or external source.';

-- migrate:down

DROP TABLE IF EXISTS raw_stock_lots CASCADE;
