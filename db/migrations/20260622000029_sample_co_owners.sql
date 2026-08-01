-- migrate:up
-- Junction table for M2M co-ownership on physical_samples.
-- No hard FK to directus_users per ADR-0002 (Directus is swappable);
-- the Directus relation config wires the M2M in the UI layer only.

CREATE TABLE sample_co_owners (
    id         UUID NOT NULL DEFAULT uuid_generate_v4(),
    sample_id  UUID NOT NULL REFERENCES physical_samples(sample_id) ON DELETE CASCADE,
    user_id    UUID NOT NULL,           -- intentionally no FK to directus_users (ADR-0002)
    CONSTRAINT sample_co_owners_pkey PRIMARY KEY (id),
    CONSTRAINT sample_co_owners_unique UNIQUE (sample_id, user_id)
);

COMMENT ON TABLE sample_co_owners IS
    'M2M junction: which Directus users are co-owners of a given physical sample.';

COMMENT ON COLUMN sample_co_owners.user_id IS
    'UUID of a directus_users record. No hard FK so the auth layer stays swappable.';

-- migrate:down
DROP TABLE IF EXISTS sample_co_owners;
