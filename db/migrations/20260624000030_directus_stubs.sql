-- migrate:up
-- Stub for tables that Directus creates at boot but that do not exist in a
-- bare CI database. Later migrations FK-reference directus_files; without
-- this stub, `dbmate up` fails on a fresh Postgres.
-- In production, Directus creates the real table long before our migrations run.

CREATE TABLE IF NOT EXISTS directus_files (
    id UUID NOT NULL PRIMARY KEY
);

-- migrate:down
-- Don't drop — Directus may own the real table. The IF NOT EXISTS in :up is
-- idempotent against both the stub and the real table.
