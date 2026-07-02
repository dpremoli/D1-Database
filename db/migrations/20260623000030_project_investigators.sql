-- migrate:up
-- Secondary investigators on a project: M2M junction table.
-- No hard FK to directus_users per ADR-0002 (auth layer stays swappable).
-- Adding someone here records their role as a secondary investigator and
-- is used by the UI to communicate that they have viewing access to all
-- items connected to the project (enforced at the application / policy layer).

CREATE TABLE project_investigators (
    id          UUID NOT NULL DEFAULT uuid_generate_v4(),
    project_id  UUID NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    user_id     UUID NOT NULL,
    CONSTRAINT project_investigators_pkey PRIMARY KEY (id),
    CONSTRAINT project_investigators_unique UNIQUE (project_id, user_id)
);

COMMENT ON TABLE project_investigators IS
    'M2M junction: Directus users who are secondary investigators on a project.';

COMMENT ON COLUMN project_investigators.user_id IS
    'UUID of a directus_users record. No hard FK so the auth layer stays swappable.';

-- migrate:down
DROP TABLE IF EXISTS project_investigators;
