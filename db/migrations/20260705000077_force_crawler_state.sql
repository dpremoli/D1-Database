-- migrate:up
-- Singleton control+status row for the force-crawler daemon (scripts/
-- force_orchestrator.py --daemon). Directus runs in a container and cannot
-- reach the archive share or spawn MATLAB itself, so the admin module cannot
-- launch host work directly. Instead: an admin edits desired_state/workers/
-- throttle/scope here via the d1-force-crawler module; a daemon process
-- running on the host (started manually: `py scripts/force_orchestrator.py
-- --daemon`) polls this row each loop and honors the live settings, writing
-- its own heartbeat/activity/counters back so the module can show it's alive.

CREATE TABLE force_crawler_state (
    id                UUID        NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    -- admin-editable desired configuration
    desired_state     VARCHAR(16) NOT NULL DEFAULT 'paused',
    workers           INTEGER     NOT NULL DEFAULT 2,
    throttle_seconds  NUMERIC     NOT NULL DEFAULT 5,
    file_like         TEXT,
    op_code_like      TEXT,
    -- daemon-written status (read-only in the UI)
    daemon_pid        INTEGER,
    daemon_started_at TIMESTAMPTZ,
    last_heartbeat_at TIMESTAMPTZ,
    current_activity  TEXT,
    processed_count   INTEGER     NOT NULL DEFAULT 0,
    error_count       INTEGER     NOT NULL DEFAULT 0,
    last_discover_at  TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT force_crawler_state_pkey PRIMARY KEY (id),
    CONSTRAINT force_crawler_state_singleton CHECK (id = '00000000-0000-0000-0000-000000000001'),
    CONSTRAINT force_crawler_state_desired_chk CHECK (desired_state IN ('running', 'paused'))
);

COMMENT ON TABLE force_crawler_state IS
    'Singleton control+status row for the host-side force-crawler daemon. Admin edits desired_state/workers/throttle/scope; the daemon (scripts/force_orchestrator.py --daemon) reads it live and reports heartbeat/activity back.';

INSERT INTO force_crawler_state (id) VALUES ('00000000-0000-0000-0000-000000000001')
ON CONFLICT (id) DO NOTHING;

-- migrate:down
DROP TABLE IF EXISTS force_crawler_state;
