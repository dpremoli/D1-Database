-- migrate:up
-- Fix FK constraints that were NO ACTION on NOT NULL columns, causing
-- INTERNAL_SERVER_ERROR in Directus when a parent record is deleted.
--
-- Strategy:
--   • CASCADE — child records lose meaning without the parent (true ownership).
--   • RESTRICT left unchanged for manufacturing_operations.method_id — deleting a
--     manufacturing method while operations still reference it is a data-integrity
--     violation that should surface as a clear error, not silently cascade.

-- ── Tool box hierarchy ────────────────────────────────────────────────────────
-- Delete box → delete its inserts → delete their edges.

ALTER TABLE cutting_inserts
    DROP CONSTRAINT cutting_inserts_tool_box_id_fkey,
    ADD  CONSTRAINT cutting_inserts_tool_box_id_fkey
        FOREIGN KEY (tool_box_id)
        REFERENCES tool_boxes (tool_box_id)
        ON DELETE CASCADE;

ALTER TABLE insert_edges
    DROP CONSTRAINT insert_edges_insert_id_fkey,
    ADD  CONSTRAINT insert_edges_insert_id_fkey
        FOREIGN KEY (insert_id)
        REFERENCES cutting_inserts (insert_id)
        ON DELETE CASCADE;

-- ── Physical samples traceability chain ───────────────────────────────────────
-- Delete sample → delete its manufacturing history, test sessions, and
-- genealogy / provenance links. The audit log retains the historical record.

ALTER TABLE manufacturing_operations
    DROP CONSTRAINT manufacturing_operations_sample_fkey,
    ADD  CONSTRAINT manufacturing_operations_sample_fkey
        FOREIGN KEY (sample_id)
        REFERENCES physical_samples (sample_id)
        ON DELETE CASCADE;

ALTER TABLE test_sessions
    DROP CONSTRAINT test_sessions_sample_fkey,
    ADD  CONSTRAINT test_sessions_sample_fkey
        FOREIGN KEY (sample_id)
        REFERENCES physical_samples (sample_id)
        ON DELETE CASCADE;

ALTER TABLE sample_genealogy
    DROP CONSTRAINT sample_genealogy_child_fkey,
    ADD  CONSTRAINT sample_genealogy_child_fkey
        FOREIGN KEY (child_sample_id)
        REFERENCES physical_samples (sample_id)
        ON DELETE CASCADE,
    DROP CONSTRAINT sample_genealogy_parent_fkey,
    ADD  CONSTRAINT sample_genealogy_parent_fkey
        FOREIGN KEY (parent_sample_id)
        REFERENCES physical_samples (sample_id)
        ON DELETE CASCADE;

ALTER TABLE sample_stock_provenance
    DROP CONSTRAINT sample_stock_provenance_sample_fkey,
    ADD  CONSTRAINT sample_stock_provenance_sample_fkey
        FOREIGN KEY (sample_id)
        REFERENCES physical_samples (sample_id)
        ON DELETE CASCADE,
    DROP CONSTRAINT sample_stock_provenance_lot_fkey,
    ADD  CONSTRAINT sample_stock_provenance_lot_fkey
        FOREIGN KEY (lot_id)
        REFERENCES raw_stock_lots (lot_id)
        ON DELETE CASCADE;

-- ── Method parameters ─────────────────────────────────────────────────────────
-- Parameters belong entirely to their method.

ALTER TABLE method_parameters
    DROP CONSTRAINT method_parameters_method_id_fkey,
    ADD  CONSTRAINT method_parameters_method_id_fkey
        FOREIGN KEY (method_id)
        REFERENCES manufacturing_methods (method_id)
        ON DELETE CASCADE;

-- migrate:down
ALTER TABLE cutting_inserts
    DROP CONSTRAINT cutting_inserts_tool_box_id_fkey,
    ADD  CONSTRAINT cutting_inserts_tool_box_id_fkey
        FOREIGN KEY (tool_box_id) REFERENCES tool_boxes (tool_box_id);

ALTER TABLE insert_edges
    DROP CONSTRAINT insert_edges_insert_id_fkey,
    ADD  CONSTRAINT insert_edges_insert_id_fkey
        FOREIGN KEY (insert_id) REFERENCES cutting_inserts (insert_id);

ALTER TABLE manufacturing_operations
    DROP CONSTRAINT manufacturing_operations_sample_fkey,
    ADD  CONSTRAINT manufacturing_operations_sample_fkey
        FOREIGN KEY (sample_id) REFERENCES physical_samples (sample_id);

ALTER TABLE test_sessions
    DROP CONSTRAINT test_sessions_sample_fkey,
    ADD  CONSTRAINT test_sessions_sample_fkey
        FOREIGN KEY (sample_id) REFERENCES physical_samples (sample_id);

ALTER TABLE sample_genealogy
    DROP CONSTRAINT sample_genealogy_child_fkey,
    ADD  CONSTRAINT sample_genealogy_child_fkey
        FOREIGN KEY (child_sample_id) REFERENCES physical_samples (sample_id),
    DROP CONSTRAINT sample_genealogy_parent_fkey,
    ADD  CONSTRAINT sample_genealogy_parent_fkey
        FOREIGN KEY (parent_sample_id) REFERENCES physical_samples (sample_id);

ALTER TABLE sample_stock_provenance
    DROP CONSTRAINT sample_stock_provenance_sample_fkey,
    ADD  CONSTRAINT sample_stock_provenance_sample_fkey
        FOREIGN KEY (sample_id) REFERENCES physical_samples (sample_id),
    DROP CONSTRAINT sample_stock_provenance_lot_fkey,
    ADD  CONSTRAINT sample_stock_provenance_lot_fkey
        FOREIGN KEY (lot_id) REFERENCES raw_stock_lots (lot_id);

ALTER TABLE method_parameters
    DROP CONSTRAINT method_parameters_method_id_fkey,
    ADD  CONSTRAINT method_parameters_method_id_fkey
        FOREIGN KEY (method_id) REFERENCES manufacturing_methods (method_id);
