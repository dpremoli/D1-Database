-- migrate:up
-- Per-run FAST (spark-plasma sintering) trace: one row per sintering operation's raw
-- machine CSV. The host importer (scripts/fast_orchestrator.py) normalises the two
-- machine formats (FCT HP D 25 / 250) into one canonical comma/US-decimal CSV via
-- scripts/fast_mapping.normalize_fast_csv, uploads it renamed to the operation code,
-- and records the series catalog + run metadata here. The d1-fast-dashboard fetches
-- the CSV and plots it. `status` doubles as the import work-queue.

CREATE TABLE fast_run_data (
    id                  UUID        NOT NULL DEFAULT uuid_generate_v4(),
    operation_id        UUID        NOT NULL REFERENCES manufacturing_operations(operation_id) ON DELETE CASCADE,
    directus_files_id   UUID        REFERENCES directus_files(id) ON DELETE SET NULL,  -- normalised <op_code>.csv
    staged_file         UUID        REFERENCES directus_files(id) ON DELETE SET NULL,  -- browser-uploaded raw awaiting normalisation
    status              VARCHAR(16) NOT NULL DEFAULT 'pending',
    error_message       TEXT,

    -- import trigger + provenance
    machine_format      VARCHAR(8),        -- '25' | '250'
    import_archive_path TEXT,              -- set to request a host read from the archive index

    -- run metadata parsed from the CSV
    plant               TEXT,
    recipe              TEXT,
    run_start           TIMESTAMPTZ,
    n_rows              INTEGER,
    duration_s          NUMERIC,

    -- series catalog [{key,label,unit,group,min,max}] driving the plot picker
    series              JSONB,
    summary             JSONB,

    processed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fast_run_data_pkey          PRIMARY KEY (id),
    CONSTRAINT fast_run_data_operation_uniq UNIQUE (operation_id),   -- one trace per FAST run (re-import updates)
    CONSTRAINT fast_run_data_status_chk
        CHECK (status IN ('pending', 'processing', 'done', 'error', 'skipped'))
);

COMMENT ON TABLE fast_run_data IS
    'Normalised FAST sintering trace per operation (canonical CSV + series catalog + run metadata). Populated by scripts/fast_orchestrator.py.';
COMMENT ON COLUMN fast_run_data.status IS 'Import work-queue: pending -> processing -> done | error | skipped.';
COMMENT ON COLUMN fast_run_data.staged_file IS 'Raw browser-uploaded CSV awaiting host normalisation (deleted after processing).';
COMMENT ON COLUMN fast_run_data.import_archive_path IS 'Archive path to read+normalise on the host (host-only access).';

CREATE INDEX fast_run_data_operation_id_idx ON fast_run_data (operation_id);
CREATE INDEX fast_run_data_status_idx        ON fast_run_data (status);

-- ── Directus registration ──────────────────────────────────────────────────────
-- Hidden collection (surfaced through the d1-fast-dashboard module), grouped under
-- manufacturing for admin browsing.
INSERT INTO directus_collections (collection, icon, note, display_template, hidden, "group", sort)
VALUES ('fast_run_data', 'insights',
        'Normalised FAST sintering trace per operation (canonical CSV + series catalog)',
        '{{operation_id}} — {{status}}', true, 'manufacturing_methods', 10)
ON CONFLICT (collection) DO NOTHING;

INSERT INTO directus_fields (collection, field, interface, display, options, display_options, width, sort, special, readonly, hidden)
SELECT collection, field, interface, display, options::json, display_options::json, width, sort, special, readonly, hidden
FROM (VALUES
    ('fast_run_data', 'status', 'select-dropdown', 'labels',
        '{"choices":[{"text":"Pending","value":"pending"},{"text":"Processing","value":"processing"},{"text":"Done","value":"done"},{"text":"Error","value":"error"},{"text":"Skipped","value":"skipped"}]}',
        NULL, 'half', 1, NULL, false, false),
    ('fast_run_data', 'operation_id', 'select-dropdown-m2o', 'related-values',
        '{"template":"{{pass_code}}","enableCreate":false}', '{"template":"{{pass_code}}"}', 'half', 2, 'm2o', false, false),
    ('fast_run_data', 'directus_files_id', 'file', 'file', NULL, NULL, 'half', 3, 'file', false, false),
    ('fast_run_data', 'staged_file', 'file', 'file', NULL, NULL, 'half', 4, 'file', false, false),
    ('fast_run_data', 'machine_format', 'input', 'raw', NULL, NULL, 'half', 5, NULL, true, false),
    ('fast_run_data', 'recipe', 'input', 'raw', NULL, NULL, 'half', 6, NULL, true, false),
    ('fast_run_data', 'run_start', 'datetime', 'datetime', NULL, NULL, 'half', 7, NULL, true, false),
    ('fast_run_data', 'duration_s', 'input', 'raw', NULL, NULL, 'half', 8, NULL, true, false),
    ('fast_run_data', 'error_message', 'input-multiline', 'raw', NULL, NULL, 'full', 9, NULL, true, false),
    ('fast_run_data', 'series', 'input-code', 'raw', NULL, NULL, 'full', 20, 'cast-json', true, true),
    ('fast_run_data', 'summary', 'input-code', 'raw', NULL, NULL, 'full', 21, 'cast-json', true, true)
) v(collection, field, interface, display, options, display_options, width, sort, special, readonly, hidden)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- O2M back-reference on the operation form.
INSERT INTO directus_fields (collection, field, interface, special, options, display, display_options, width, sort, hidden)
SELECT 'manufacturing_operations', 'fast_run', 'list-o2m', 'o2m',
       '{"template":"{{status}} — {{recipe}}","enableCreate":false,"enableSelect":false}',
       'related-values', '{"template":"{{status}}"}', 'full', 51, false
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f
    WHERE f.collection = 'manufacturing_operations' AND f.field = 'fast_run'
);

INSERT INTO directus_relations (many_collection, many_field, one_collection, one_field, one_deselect_action)
SELECT 'fast_run_data', 'operation_id', 'manufacturing_operations', 'fast_run', 'delete'
WHERE NOT EXISTS (
    SELECT 1 FROM directus_relations r
    WHERE r.many_collection = 'fast_run_data' AND r.many_field = 'operation_id'
);

INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action)
SELECT 'fast_run_data', v.fld, 'directus_files', 'nullify'
FROM (VALUES ('directus_files_id'), ('staged_file')) v(fld)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_relations r
    WHERE r.many_collection = 'fast_run_data' AND r.many_field = v.fld
);

-- Lab Member: read-only (dashboard consumption).
INSERT INTO directus_permissions (policy, collection, action, permissions, validation, fields)
SELECT '20000002-0000-0000-0000-000000000002', 'fast_run_data', 'read', '{}', '{}', '*'
WHERE NOT EXISTS (
    SELECT 1 FROM directus_permissions p
    WHERE p.policy = '20000002-0000-0000-0000-000000000002'
      AND p.collection = 'fast_run_data' AND p.action = 'read'
);

-- migrate:down
DELETE FROM directus_permissions WHERE collection = 'fast_run_data' AND policy = '20000002-0000-0000-0000-000000000002';
DELETE FROM directus_relations   WHERE many_collection = 'fast_run_data';
DELETE FROM directus_fields      WHERE collection = 'manufacturing_operations' AND field = 'fast_run';
DELETE FROM directus_fields      WHERE collection = 'fast_run_data';
DELETE FROM directus_collections WHERE collection = 'fast_run_data';
DROP TABLE IF EXISTS fast_run_data;