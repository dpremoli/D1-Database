-- migrate:up
-- Drop the method_parameters reference catalog. It was a template describing
-- which JSONB keys were expected in manufacturing_operations.recorded_metadata,
-- but parameters now live as typed inline columns on manufacturing_operations
-- (see 20260623000032_inline_param_fields.sql), so this table is superseded.
-- No table references it (its only FK was outbound, to manufacturing_methods).

DROP TABLE IF EXISTS method_parameters;

-- migrate:down
-- Recreate the table as it stood after 20260621000023_cascade_deletes.sql
-- (ON DELETE CASCADE on the method_id FK). Data is not restored.
CREATE TABLE method_parameters (
    parameter_id    UUID        NOT NULL DEFAULT uuid_generate_v4(),
    method_id       UUID        NOT NULL,
    parameter_name  TEXT        NOT NULL,
    display_name    TEXT        NOT NULL,
    data_type       TEXT        NOT NULL,
    unit_of_measure TEXT,
    is_required     BOOLEAN     NOT NULL DEFAULT FALSE,
    sort_order      INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT method_parameters_pkey PRIMARY KEY (parameter_id),
    CONSTRAINT method_parameters_method_param_unique UNIQUE (method_id, parameter_name),
    CONSTRAINT method_parameters_method_id_fkey
        FOREIGN KEY (method_id)
        REFERENCES manufacturing_methods (method_id)
        ON DELETE CASCADE,
    CONSTRAINT method_parameters_data_type_check
        CHECK (data_type IN ('numeric', 'integer', 'text', 'boolean', 'file_uri', 'timestamp'))
);

COMMENT ON TABLE method_parameters
    IS 'Template: which JSONB keys are expected in manufacturing_operations.recorded_metadata';
