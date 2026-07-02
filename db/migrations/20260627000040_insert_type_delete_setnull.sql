-- migrate:up
-- Align the cutting_inserts → insert_types FK with its intended delete behavior.
-- The column is nullable and the Directus relation is configured to "nullify",
-- but the DB constraint was left at NO ACTION (migration 023 only converted the
-- tool_box_id FK), so deleting an insert_type was blocked by the FK.
-- insert_types is the catalog; cutting_inserts are the physical inserts of that
-- type. Deleting a catalog type should UNLINK the physical inserts (set type to
-- NULL), not delete the physical inventory (which belongs to its box, not its
-- type — that relationship cascades from tool_boxes).

ALTER TABLE cutting_inserts
    DROP CONSTRAINT cutting_inserts_insert_type_id_fkey,
    ADD  CONSTRAINT cutting_inserts_insert_type_id_fkey
        FOREIGN KEY (insert_type_id)
        REFERENCES insert_types (insert_type_id)
        ON DELETE SET NULL;

-- migrate:down
ALTER TABLE cutting_inserts
    DROP CONSTRAINT cutting_inserts_insert_type_id_fkey,
    ADD  CONSTRAINT cutting_inserts_insert_type_id_fkey
        FOREIGN KEY (insert_type_id)
        REFERENCES insert_types (insert_type_id);
