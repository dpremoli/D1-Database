-- migrate:up
-- Stub for tables that Directus creates at boot but that do not exist in a
-- bare CI database. Later migrations FK-reference directus_files; without
-- this stub, `dbmate up` fails on a fresh Postgres.
-- In production, Directus creates the real table long before our migrations run.

CREATE TABLE IF NOT EXISTS directus_files (
    id UUID NOT NULL PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS directus_users (
    id UUID NOT NULL PRIMARY KEY,
    email TEXT,
    first_name TEXT
);

CREATE TABLE IF NOT EXISTS "Machine_Operators" (
    id INTEGER NOT NULL PRIMARY KEY,
    "Name" TEXT
);

-- manufacturing_operations.operator is a Directus-managed column (INTEGER FK to
-- Machine_Operators) that was added via the admin UI, not a migration. Later
-- migrations (0038, 0061) UPDATE it, so it must exist in CI.
ALTER TABLE manufacturing_operations
    ADD COLUMN IF NOT EXISTS operator INTEGER
        REFERENCES "Machine_Operators"(id) ON DELETE SET NULL;

-- migrate:down
-- Don't drop — Directus may own the real table. The IF NOT EXISTS in :up is
-- idempotent against both the stub and the real table.
