-- migrate:up
-- Keep test_sessions.sample_id / insert_edge_id in step with the M2A junction test_sessions_subject.
--
-- Why: migration 063 moved a test's target into the junction test_sessions_subject, and 064 hid
-- test_sessions.sample_id / insert_edge_id in the Directus form, so tests created through the form
-- leave both columns NULL. Every reader that still goes through sample_id (the campaign matrix,
-- the d1-report sample and test reports, the lineage graph, SampleDashboard, f_sample_timeline,
-- the TestsPanel search) therefore misses those tests. Rather than teach each reader the junction,
-- the columns become a derived "primary subject" denormalisation:
--   sample_id      = the first physical_samples subject of the test (lowest junction id)
--   insert_edge_id = the first insert_edges subject of the test (lowest junction id)
-- Tests with several samples keep only the first in sample_id; readers that need all of them must
-- read the junction (the Sample page does).
-- "Lowest id" is deterministic but not insertion order (ids are random UUIDs): the junction has
-- no timestamp to order by.
--
-- Deleting subjects: see the second half of this file. Since sample_id is now filled for every
-- test and test_sessions_sample_fkey is ON DELETE CASCADE (migration 023), deleting a test's
-- primary sample would destroy the test and its links to its other samples. The cascade is
-- replaced by a trigger that keeps the test while it has another subject.
--
-- An item that is not a valid uuid, or names a sample / edge that no longer exists, is skipped
-- (the junction item is a VARCHAR with no FK). test_sessions is only updated when the derived
-- value really changes, because its OCC and audit triggers fire on every UPDATE.

CREATE OR REPLACE FUNCTION sync_test_session_primary_subject(p_session_id UUID)
    RETURNS VOID
    LANGUAGE plpgsql
AS $$
DECLARE
    v_uuid_re CONSTANT TEXT := '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
    v_sample  UUID;
    v_edge    UUID;
    r         RECORD;
BEGIN
    IF p_session_id IS NULL THEN
        RETURN;
    END IF;

    -- Serialise concurrent subject changes of one test: without the lock two transactions that
    -- each add or remove a subject could both read the junction before the other committed and
    -- the last writer would store a stale primary subject. Waits for any other transaction that
    -- is syncing (or editing) this test; a test row that is already gone is simply not locked.
    PERFORM 1 FROM test_sessions WHERE session_id = p_session_id FOR UPDATE;

    FOR r IN
        SELECT s.item
        FROM test_sessions_subject s
        WHERE s.test_sessions_id = p_session_id AND s.collection = 'physical_samples'
        ORDER BY s.id
    LOOP
        IF r.item ~* v_uuid_re
           AND EXISTS (SELECT 1 FROM physical_samples p WHERE p.sample_id = r.item::uuid) THEN
            v_sample := r.item::uuid;
            EXIT;
        END IF;
    END LOOP;

    FOR r IN
        SELECT s.item
        FROM test_sessions_subject s
        WHERE s.test_sessions_id = p_session_id AND s.collection = 'insert_edges'
        ORDER BY s.id
    LOOP
        IF r.item ~* v_uuid_re
           AND EXISTS (SELECT 1 FROM insert_edges e WHERE e.edge_id = r.item::uuid) THEN
            v_edge := r.item::uuid;
            EXIT;
        END IF;
    END LOOP;

    UPDATE test_sessions
    SET sample_id = v_sample,
        insert_edge_id = v_edge
    WHERE session_id = p_session_id
      AND (sample_id IS DISTINCT FROM v_sample OR insert_edge_id IS DISTINCT FROM v_edge);
END;
$$;

COMMENT ON FUNCTION sync_test_session_primary_subject(UUID) IS
    'Recomputes test_sessions.sample_id and insert_edge_id (derived from test_sessions_subject (primary subject); do not write directly) for one test.';

CREATE OR REPLACE FUNCTION trg_test_sessions_subject_sync_primary()
    RETURNS TRIGGER
    LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        PERFORM sync_test_session_primary_subject(NEW.test_sessions_id);
    END IF;
    IF TG_OP = 'DELETE'
       OR (TG_OP = 'UPDATE' AND OLD.test_sessions_id IS DISTINCT FROM NEW.test_sessions_id) THEN
        PERFORM sync_test_session_primary_subject(OLD.test_sessions_id);
    END IF;
    RETURN NULL;
END;
$$;

COMMENT ON FUNCTION trg_test_sessions_subject_sync_primary() IS
    'Trigger function: keeps test_sessions.sample_id / insert_edge_id derived from test_sessions_subject (primary subject); do not write directly.';

CREATE TRIGGER test_sessions_subject_sync_primary
    AFTER INSERT OR UPDATE OR DELETE ON test_sessions_subject
    FOR EACH ROW EXECUTE FUNCTION trg_test_sessions_subject_sync_primary();

COMMENT ON TRIGGER test_sessions_subject_sync_primary ON test_sessions_subject IS
    'Recomputes the parent test''s sample_id / insert_edge_id: derived from test_sessions_subject (primary subject); do not write directly.';

COMMENT ON COLUMN test_sessions.sample_id IS
    'The first sample under test, derived from test_sessions_subject (primary subject); do not write directly. A test with several samples needs the junction.';
COMMENT ON COLUMN test_sessions.insert_edge_id IS
    'The first cutting edge under test, derived from test_sessions_subject (primary subject); do not write directly.';

-- Back-fill. First re-run migration 063's two copies so every direct sample_id / insert_edge_id
-- is in the junction (a writer since 063 may have set the columns directly, and the sync derives
-- the columns from the junction: without this a test with a direct sample and an edge-only junction
-- would lose its sample). Then derive the columns for every test that has junction rows. Tests
-- with no junction row keep whatever a direct writer put in sample_id / insert_edge_id.
INSERT INTO test_sessions_subject (test_sessions_id, collection, item)
SELECT session_id, 'physical_samples', sample_id::text
FROM test_sessions
WHERE sample_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM test_sessions_subject s
                  WHERE s.test_sessions_id = test_sessions.session_id
                    AND s.collection = 'physical_samples' AND lower(s.item) = test_sessions.sample_id::text);

INSERT INTO test_sessions_subject (test_sessions_id, collection, item)
SELECT session_id, 'insert_edges', insert_edge_id::text
FROM test_sessions
WHERE insert_edge_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM test_sessions_subject s
                  WHERE s.test_sessions_id = test_sessions.session_id
                    AND s.collection = 'insert_edges' AND lower(s.item) = test_sessions.insert_edge_id::text);

SELECT sync_test_session_primary_subject(t.session_id)
FROM test_sessions t
WHERE EXISTS (SELECT 1 FROM test_sessions_subject s WHERE s.test_sessions_id = t.session_id);

-- Deleting a sample.
--
-- test_sessions_sample_fkey was ON DELETE CASCADE (migration 023: a test belongs to its sample).
-- Now that sample_id is the primary subject of every test, the cascade would delete a test
-- (and its links to its OTHER samples) as soon as its primary sample goes, and which sample is
-- primary depends on random junction uuids. The FK becomes ON DELETE SET NULL, and a BEFORE
-- DELETE trigger on physical_samples keeps the original intent: a test is deleted with its
-- sample only when that sample was its last subject.
--   1. every junction row naming the sample is deleted; the sync trigger above then promotes the
--      test's next sample as primary;
--   2. a test that was affected (its sample_id was this sample, or it lost a junction row) and
--      has no subject left at all (no physical_samples or insert_edges junction row, no
--      insert_edge_id) is deleted, as the cascade used to do. Its junction rows go with it.
-- BEFORE, not AFTER: the foreign key's SET NULL action runs after the row is deleted and would
-- already have blanked sample_id, so an AFTER trigger could no longer tell which tests used the
-- sample directly (legacy tests with no junction row). Running before the delete also means the
-- SET NULL then only touches the tests that survive with some other subject.
CREATE OR REPLACE FUNCTION trg_physical_samples_delete_test_subjects()
    RETURNS TRIGGER
    LANGUAGE plpgsql
AS $$
DECLARE
    v_tests UUID[];
BEGIN
    SELECT COALESCE(array_agg(DISTINCT t.session_id), '{}')
      INTO v_tests
      FROM test_sessions t
     WHERE t.sample_id = OLD.sample_id;

    WITH del AS (
        DELETE FROM test_sessions_subject s
         WHERE s.collection = 'physical_samples'
           AND lower(s.item) = OLD.sample_id::text
        RETURNING s.test_sessions_id
    )
    SELECT v_tests || COALESCE(array_agg(DISTINCT del.test_sessions_id), '{}')
      INTO v_tests
      FROM del;

    DELETE FROM test_sessions t
     WHERE t.session_id = ANY (v_tests)
       AND t.insert_edge_id IS NULL
       AND NOT EXISTS (SELECT 1 FROM test_sessions_subject s
                       WHERE s.test_sessions_id = t.session_id
                         AND s.collection IN ('physical_samples', 'insert_edges'));
    RETURN OLD;
END;
$$;

COMMENT ON FUNCTION trg_physical_samples_delete_test_subjects() IS
    'Trigger function (BEFORE DELETE on physical_samples): removes the sample from every test subject list and deletes the tests that have no subject left.';

CREATE TRIGGER physical_samples_delete_test_subjects
    BEFORE DELETE ON physical_samples
    FOR EACH ROW EXECUTE FUNCTION trg_physical_samples_delete_test_subjects();

COMMENT ON TRIGGER physical_samples_delete_test_subjects ON physical_samples IS
    'Deleting a sample removes it from tests'' subject lists (the next sample becomes primary) and deletes the tests left with no subject.';

ALTER TABLE test_sessions
    DROP CONSTRAINT test_sessions_sample_fkey,
    ADD  CONSTRAINT test_sessions_sample_fkey
        FOREIGN KEY (sample_id)
        REFERENCES physical_samples (sample_id)
        ON DELETE SET NULL;

-- Deleting an insert edge.
--
-- test_sessions_insert_edge_fkey has no ON DELETE action (migration 008), so an edge that a test
-- names in insert_edge_id cannot be deleted; that FK still blocks it. An edge named only by a
-- junction row would now slip through (the junction item has no FK) and leave a dangling subject,
-- so this trigger gives the same answer, with a readable message. It also blocks the cascades
-- from deleting a cutting insert or a tool box that reach such an edge: remove the edge from the
-- test first.
CREATE OR REPLACE FUNCTION trg_insert_edges_block_subject_delete()
    RETURNS TRIGGER
    LANGUAGE plpgsql
AS $$
DECLARE
    v_test UUID;
BEGIN
    SELECT s.test_sessions_id INTO v_test
      FROM test_sessions_subject s
     WHERE s.collection = 'insert_edges' AND lower(s.item) = OLD.edge_id::text
     LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION 'insert edge % (%) is the subject of test %; remove it from the test first',
            OLD.edge_code, OLD.edge_id, v_test
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    RETURN OLD;
END;
$$;

COMMENT ON FUNCTION trg_insert_edges_block_subject_delete() IS
    'Trigger function (BEFORE DELETE on insert_edges): refuses to delete an edge that a test names as its subject in test_sessions_subject.';

CREATE TRIGGER insert_edges_block_subject_delete
    BEFORE DELETE ON insert_edges
    FOR EACH ROW EXECUTE FUNCTION trg_insert_edges_block_subject_delete();

COMMENT ON TRIGGER insert_edges_block_subject_delete ON insert_edges IS
    'Refuses to delete an edge that a test names as its subject (like test_sessions_insert_edge_fkey does for the insert_edge_id column).';

-- migrate:down
-- The values the trigger back-filled are left in place: they are correct data and the columns are
-- nullable, so nothing needs undoing. The column comments return to the originals (migration 008).
-- The sample foreign key returns to ON DELETE CASCADE (migration 023) and the delete triggers go.
DROP TRIGGER IF EXISTS insert_edges_block_subject_delete ON insert_edges;
DROP FUNCTION IF EXISTS trg_insert_edges_block_subject_delete();
DROP TRIGGER IF EXISTS physical_samples_delete_test_subjects ON physical_samples;
DROP FUNCTION IF EXISTS trg_physical_samples_delete_test_subjects();
ALTER TABLE test_sessions
    DROP CONSTRAINT test_sessions_sample_fkey,
    ADD  CONSTRAINT test_sessions_sample_fkey
        FOREIGN KEY (sample_id)
        REFERENCES physical_samples (sample_id)
        ON DELETE CASCADE;
DROP TRIGGER IF EXISTS test_sessions_subject_sync_primary ON test_sessions_subject;
DROP FUNCTION IF EXISTS trg_test_sessions_subject_sync_primary();
DROP FUNCTION IF EXISTS sync_test_session_primary_subject(UUID);
COMMENT ON COLUMN test_sessions.sample_id
    IS 'The sample under test. FK to physical_samples.';
COMMENT ON COLUMN test_sessions.insert_edge_id
    IS 'The specific cutting-edge used in this test. FK to insert_edges.';
