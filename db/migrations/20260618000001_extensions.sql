-- migrate:up

-- pgvector: vector-similarity search (Phase 6 embeddings).
CREATE EXTENSION IF NOT EXISTS vector;

-- uuid-ossp: uuid_generate_v4() for primary keys.
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- pg_trgm: trigram indexes for fast fuzzy text search on codes / names.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- migrate:down

DROP EXTENSION IF EXISTS pg_trgm;
DROP EXTENSION IF EXISTS "uuid-ossp";
DROP EXTENSION IF EXISTS vector;
