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

-- Back-fill: every test that has junction rows. Tests with no junction row keep whatever a direct
-- writer (older scripts, imports) put in sample_id / insert_edge_id.
SELECT sync_test_session_primary_subject(t.session_id)
FROM test_sessions t
WHERE EXISTS (SELECT 1 FROM test_sessions_subject s WHERE s.test_sessions_id = t.session_id);

-- migrate:down
-- The values the trigger back-filled are left in place: they are correct data and the columns are
-- nullable, so nothing needs undoing. The column comments return to the originals (migration 008).
DROP TRIGGER IF EXISTS test_sessions_subject_sync_primary ON test_sessions_subject;
DROP FUNCTION IF EXISTS trg_test_sessions_subject_sync_primary();
DROP FUNCTION IF EXISTS sync_test_session_primary_subject(UUID);
COMMENT ON COLUMN test_sessions.sample_id
    IS 'The sample under test. FK to physical_samples.';
COMMENT ON COLUMN test_sessions.insert_edge_id
    IS 'The specific cutting-edge used in this test. FK to insert_edges.';
