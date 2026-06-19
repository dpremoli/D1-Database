-- migrate:up
-- Unify the test_sessions.status vocabulary across the schema, the heavy-data
-- worker, the analysis worker, and the plugin template.
--
-- The original constraint (migration ...0008) allowed only
--   {registered, processing, complete, failed}
-- but the asynchronous workers and the Phase 4 integration test write a richer
-- set of lifecycle states (pending_processing, processed, analysing, analysed).
-- Every successful write-back therefore violated the CHECK constraint. This
-- migration replaces the constraint with the canonical lifecycle and is the
-- single source of truth mirrored by app/lib/statuses.py in each plugin.
--
-- Canonical lifecycle:
--   registered → pending_processing → processing → processed
--              → analysing → analysed
--   (terminal failure: failed)

ALTER TABLE test_sessions DROP CONSTRAINT test_sessions_status_check;

ALTER TABLE test_sessions ADD CONSTRAINT test_sessions_status_check
    CHECK (status IN (
        'registered',
        'pending_processing',
        'processing',
        'processed',
        'analysing',
        'analysed',
        'failed'
    ));

COMMENT ON COLUMN test_sessions.status
    IS 'Pipeline lifecycle status. Canonical set (see db migration 0013 and each'
       ' plugin app/lib/statuses.py): registered | pending_processing | processing |'
       ' processed | analysing | analysed | failed.';

-- migrate:down

ALTER TABLE test_sessions DROP CONSTRAINT test_sessions_status_check;

ALTER TABLE test_sessions ADD CONSTRAINT test_sessions_status_check
    CHECK (status IN ('registered', 'processing', 'complete', 'failed'));

COMMENT ON COLUMN test_sessions.status
    IS 'Pipeline status: registered | processing | complete | failed.';
