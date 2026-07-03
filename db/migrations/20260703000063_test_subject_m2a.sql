-- migrate:up
-- ③ Testable subject (polymorphic M2A), step 1 of 2: junction + data migration.
--
-- A test currently targets a physical_sample (sample_id, NOT NULL) with a separate
-- optional insert_edge_id. That forces two fields and can't grow to new testable
-- things. Replace them with one Many-to-Any "subject": a test points at a
-- physical_sample OR an insert_edge (or future targets) through a junction.
--
-- The old sample_id / insert_edge_id columns are kept (nullable) as a backup until
-- verified. sample_id loses its NOT NULL so a subject-only test is valid.

CREATE TABLE IF NOT EXISTS test_sessions_subject (
    id                UUID        NOT NULL DEFAULT uuid_generate_v4(),
    test_sessions_id  UUID        NOT NULL REFERENCES test_sessions(session_id) ON DELETE CASCADE,
    collection        VARCHAR(64) NOT NULL,
    item              VARCHAR(255) NOT NULL,
    CONSTRAINT test_sessions_subject_pkey PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS test_sessions_subject_parent_idx ON test_sessions_subject(test_sessions_id);
CREATE INDEX IF NOT EXISTS test_sessions_subject_target_idx ON test_sessions_subject(collection, item);

COMMENT ON TABLE test_sessions_subject IS
    'M2A junction: the subject(s) a test targets — a physical_sample, an insert_edge, or a future testable collection.';

-- Migrate existing subjects: sample_id → physical_samples, insert_edge_id → insert_edges.
INSERT INTO test_sessions_subject (test_sessions_id, collection, item)
SELECT session_id, 'physical_samples', sample_id::text
FROM test_sessions
WHERE sample_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM test_sessions_subject s
                  WHERE s.test_sessions_id = test_sessions.session_id
                    AND s.collection = 'physical_samples' AND s.item = test_sessions.sample_id::text);

INSERT INTO test_sessions_subject (test_sessions_id, collection, item)
SELECT session_id, 'insert_edges', insert_edge_id::text
FROM test_sessions
WHERE insert_edge_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM test_sessions_subject s
                  WHERE s.test_sessions_id = test_sessions.session_id
                    AND s.collection = 'insert_edges' AND s.item = test_sessions.insert_edge_id::text);

-- Allow subject-only tests (no legacy sample_id).
ALTER TABLE test_sessions ALTER COLUMN sample_id DROP NOT NULL;

-- migrate:down
ALTER TABLE test_sessions ALTER COLUMN sample_id SET NOT NULL;
DROP TABLE IF EXISTS test_sessions_subject CASCADE;
