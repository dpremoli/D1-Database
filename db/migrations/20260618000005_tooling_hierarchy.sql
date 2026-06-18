-- migrate:up
-- Three-level tooling hierarchy confirmed exact from legacy data:
-- tool_boxes (grandparent) → cutting_inserts (parent) → insert_edges (child).
-- Machining operations and test sessions reference insert_edges directly.
-- See docs/legacy-data-analysis.md §3.

-- ---------------------------------------------------------------------------
-- Level 1: Tool boxes — storage containers for insert batches.
-- ---------------------------------------------------------------------------
CREATE TABLE tool_boxes (
    tool_box_id     UUID        NOT NULL DEFAULT uuid_generate_v4(),
    tool_box_code   VARCHAR(64) NOT NULL,
    description     TEXT,
    location        TEXT,
    insert_type_id  UUID,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version         INTEGER     NOT NULL DEFAULT 1,
    CONSTRAINT tool_boxes_pkey PRIMARY KEY (tool_box_id),
    CONSTRAINT tool_boxes_code_unique UNIQUE (tool_box_code),
    CONSTRAINT tool_boxes_insert_type_id_fkey
        FOREIGN KEY (insert_type_id)
        REFERENCES insert_types (insert_type_id)
);

COMMENT ON TABLE tool_boxes
    IS 'Grandparent level of the 3-tier tooling hierarchy.'
       ' A box holds a batch of identical cutting inserts.';
COMMENT ON COLUMN tool_boxes.tool_box_code
    IS 'Unique label on the physical box, e.g. BOX-H13A-001.';
COMMENT ON COLUMN tool_boxes.insert_type_id
    IS 'Default insert type for this box. Individual inserts may override.';

-- ---------------------------------------------------------------------------
-- Level 2: Cutting inserts — individual multi-edged inserts.
-- Dual identity: insert_id (UUID PK) + insert_code (human-readable, e.g. H13A-#2).
-- ---------------------------------------------------------------------------
CREATE TABLE cutting_inserts (
    insert_id       UUID        NOT NULL DEFAULT uuid_generate_v4(),
    insert_code     VARCHAR(64) NOT NULL,
    tool_box_id     UUID        NOT NULL,
    insert_type_id  UUID,
    insert_number   INTEGER,
    is_depleted     BOOLEAN     NOT NULL DEFAULT FALSE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version         INTEGER     NOT NULL DEFAULT 1,
    CONSTRAINT cutting_inserts_pkey PRIMARY KEY (insert_id),
    CONSTRAINT cutting_inserts_code_unique UNIQUE (insert_code),
    CONSTRAINT cutting_inserts_tool_box_id_fkey
        FOREIGN KEY (tool_box_id)
        REFERENCES tool_boxes (tool_box_id),
    CONSTRAINT cutting_inserts_insert_type_id_fkey
        FOREIGN KEY (insert_type_id)
        REFERENCES insert_types (insert_type_id)
);

COMMENT ON TABLE cutting_inserts
    IS 'Parent level of the tooling hierarchy. One physical insert with N edges.'
       ' insert_code is the human-readable pseudonym (e.g. H13A-#2).';
COMMENT ON COLUMN cutting_inserts.insert_code
    IS 'Human-readable code: type-insert# (e.g. H13A-#2). Unique. Never the PK.';
COMMENT ON COLUMN cutting_inserts.insert_number
    IS 'Sequential number of this insert within its tool_box.';
COMMENT ON COLUMN cutting_inserts.is_depleted
    IS 'TRUE when all edges of this insert have been consumed.';

-- ---------------------------------------------------------------------------
-- Level 3: Insert edges — discrete cutting points on an insert.
-- Dual identity: edge_id (UUID PK) + edge_code (human-readable, e.g. H13A-#2-fC).
-- ---------------------------------------------------------------------------
CREATE TABLE insert_edges (
    edge_id         UUID        NOT NULL DEFAULT uuid_generate_v4(),
    edge_code       VARCHAR(64) NOT NULL,
    insert_id       UUID        NOT NULL,
    edge_identifier VARCHAR(16) NOT NULL,
    is_used         BOOLEAN     NOT NULL DEFAULT FALSE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version         INTEGER     NOT NULL DEFAULT 1,
    CONSTRAINT insert_edges_pkey PRIMARY KEY (edge_id),
    CONSTRAINT insert_edges_code_unique UNIQUE (edge_code),
    CONSTRAINT insert_edges_insert_id_fkey
        FOREIGN KEY (insert_id)
        REFERENCES cutting_inserts (insert_id)
);

COMMENT ON TABLE insert_edges
    IS 'Child level of the tooling hierarchy. Each physical cutting point on an insert.'
       ' edge_code is the human-readable pseudonym (e.g. H13A-#2-fC).';
COMMENT ON COLUMN insert_edges.edge_code
    IS 'Human-readable code: type-insert#-edge (e.g. H13A-#2-fC). Unique.';
COMMENT ON COLUMN insert_edges.edge_identifier
    IS 'Single edge label within the insert, e.g. A, B, fC, fA. Not globally unique.';
COMMENT ON COLUMN insert_edges.is_used
    IS 'TRUE once this edge has been consumed by a machining pass.';

-- migrate:down

DROP TABLE IF EXISTS insert_edges CASCADE;
DROP TABLE IF EXISTS cutting_inserts CASCADE;
DROP TABLE IF EXISTS tool_boxes CASCADE;
