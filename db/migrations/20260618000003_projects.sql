-- migrate:up
-- Projects / campaigns group manufacturing operations and test sessions.
-- Example: AI4340 = "AI4340 – FAST Rolled Plate Detection" with AMRC GESS
-- controlled-document numbering. Identified in docs/experiment-sheets-and-naming.md.

CREATE TABLE projects (
    project_id                      UUID        NOT NULL DEFAULT uuid_generate_v4(),
    project_code                    VARCHAR(32) NOT NULL,
    project_name                    TEXT        NOT NULL,
    description                     TEXT,
    document_number                 TEXT,
    principal_investigator_name     TEXT,
    start_date                      DATE,
    end_date                        DATE,
    export_controlled               BOOLEAN     NOT NULL DEFAULT FALSE,
    is_active                       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    version                         INTEGER     NOT NULL DEFAULT 1,
    CONSTRAINT projects_pkey PRIMARY KEY (project_id),
    CONSTRAINT projects_code_unique UNIQUE (project_code)
);

COMMENT ON TABLE projects
    IS 'Research campaigns / projects grouping related operations and test sessions.'
       ' E.g. AI4340 – FAST Rolled Plate Detection.';
COMMENT ON COLUMN projects.project_code
    IS 'Short unique identifier, e.g. AI4340. Used in document numbering.';
COMMENT ON COLUMN projects.document_number
    IS 'AMRC GESS controlled-document number, e.g. AI4340-AMRC-ES-230323-01.';
COMMENT ON COLUMN projects.export_controlled
    IS 'TRUE if the project is subject to ITAR/ECJU controls. Propagates to samples.';

-- migrate:down

DROP TABLE IF EXISTS projects CASCADE;
