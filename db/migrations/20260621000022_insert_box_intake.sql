-- migrate:up
-- Auto-expansion of insert box deliveries.
--
-- Workflow: user fills in ONE tool_box form row with package_quantity = N.
-- The Directus box-intake hook calls expand_tool_box_intake(box_id) which:
--   1. Generates short human-readable codes from insert_types.short_code.
--   2. Creates N tool_box rows (updating the first, inserting N-1 more).
--   3. For each box: inserts insert_types.inserts_per_box cutting_inserts.
--   4. For each insert: inserts insert_types.edge_count insert_edges (A, B, C …).
--
-- Code pattern: {short_code}-{box_seq}-{insert_pos}{edge_letter}
--   e.g.  CCMT09-1, CCMT09-1-3, CCMT09-1-3B

-- ── short_code on insert_types ────────────────────────────────────────────────
ALTER TABLE insert_types
    ADD COLUMN IF NOT EXISTS short_code VARCHAR(16);

COMMENT ON COLUMN insert_types.short_code IS
    'Short 4-8 char prefix used in auto-generated box/insert/edge codes (e.g. CCMT09). '
    'Auto-derived from type_code on first intake if left blank. '
    'Two types may not share the same short_code.';

CREATE UNIQUE INDEX IF NOT EXISTS insert_types_short_code_unique
    ON insert_types (short_code)
    WHERE short_code IS NOT NULL;

-- Backfill for any insert types that already exist, avoiding collisions.
DO $$
DECLARE
    r         RECORD;
    base_code TEXT;
    candidate TEXT;
    counter   INTEGER;
BEGIN
    FOR r IN
        SELECT insert_type_id, type_code
        FROM   insert_types
        WHERE  short_code IS NULL
        ORDER  BY created_at
    LOOP
        base_code := LEFT(REGEXP_REPLACE(r.type_code, '[^A-Za-z0-9]', '', 'g'), 6);
        candidate := base_code;
        counter   := 2;
        WHILE EXISTS (
            SELECT 1 FROM insert_types
            WHERE  short_code = candidate
              AND  insert_type_id <> r.insert_type_id
        ) LOOP
            candidate := LEFT(base_code, 5) || counter;
            counter   := counter + 1;
        END LOOP;
        UPDATE insert_types SET short_code = candidate
        WHERE  insert_type_id = r.insert_type_id;
    END LOOP;
END $$;

-- ── tool_box_code placeholder default ─────────────────────────────────────────
-- Allows the intake form to omit tool_box_code; the expansion function overwrites
-- the placeholder with the proper hierarchical code.
ALTER TABLE tool_boxes
    ALTER COLUMN tool_box_code SET DEFAULT 'TMP-' || uuid_generate_v4()::TEXT;

-- Clarify package_quantity semantics.
COMMENT ON COLUMN tool_boxes.package_quantity IS
    'Number of boxes received in this delivery (intake batch size). '
    'expand_tool_box_intake() creates this many box records plus their inserts and edges. '
    'Set to 0 or NULL to skip auto-expansion (manual entry or legacy import).';

-- ── Helper: safe 6-char prefix from free-text type code ───────────────────────
CREATE OR REPLACE FUNCTION generate_insert_short_code(p_type_code TEXT)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE STRICT
AS $$
    SELECT LEFT(REGEXP_REPLACE(p_type_code, '[^A-Za-z0-9]', '', 'g'), 6)
$$;

COMMENT ON FUNCTION generate_insert_short_code(TEXT) IS
    'Strips non-alphanumeric chars from p_type_code and returns the first 6 characters. '
    'Used as a fallback when insert_types.short_code is not set.';

-- ── Main expansion function ───────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION expand_tool_box_intake(p_first_box_id UUID)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_box          tool_boxes%ROWTYPE;
    v_it           insert_types%ROWTYPE;
    v_short_code   TEXT;
    v_base_seq     INTEGER;   -- boxes of this type that existed before this batch
    v_box_seq      INTEGER;
    v_box_id       UUID;
    v_box_code     TEXT;
    v_insert_id    UUID;
    v_insert_code  TEXT;
    -- Supports up to 20 edges per insert (A–T). Extend if needed.
    v_edge_letters TEXT[] := ARRAY[
        'A','B','C','D','E','F','G','H','I','J',
        'K','L','M','N','O','P','Q','R','S','T'
    ];
    v_ins_num      INTEGER;
    v_edge_idx     INTEGER;
BEGIN
    -- Fetch the box Directus just created.
    SELECT * INTO v_box FROM tool_boxes WHERE tool_box_id = p_first_box_id;
    IF NOT FOUND OR v_box.insert_type_id IS NULL THEN
        RETURN;  -- nothing to expand without an insert type
    END IF;

    -- Lock the insert_type row to serialise concurrent intakes of the same type,
    -- preventing box-sequence collisions under simultaneous writes.
    SELECT * INTO v_it
    FROM   insert_types
    WHERE  insert_type_id = v_box.insert_type_id
    FOR UPDATE;

    -- Resolve short code: explicit field preferred, auto-derive as fallback.
    v_short_code := COALESCE(
        NULLIF(TRIM(v_it.short_code), ''),
        generate_insert_short_code(v_it.type_code)
    );
    IF v_short_code IS NULL OR v_short_code = '' THEN
        RAISE EXCEPTION 'expand_tool_box_intake: cannot derive short_code for insert_type %', v_box.insert_type_id;
    END IF;

    -- Base sequence = boxes of this type that existed BEFORE this batch.
    SELECT COUNT(*) INTO v_base_seq
    FROM   tool_boxes
    WHERE  insert_type_id = v_box.insert_type_id
      AND  tool_box_id   <> p_first_box_id;

    -- Create N boxes (1..package_quantity). Box 1 = the row Directus created.
    FOR v_box_seq IN 1 .. GREATEST(COALESCE(v_box.package_quantity, 1), 1) LOOP

        v_box_code := v_short_code || '-' || (v_base_seq + v_box_seq);

        IF v_box_seq = 1 THEN
            -- Overwrite the placeholder code on the first (existing) box.
            UPDATE tool_boxes
            SET    tool_box_code = v_box_code
            WHERE  tool_box_id   = p_first_box_id;
            v_box_id := p_first_box_id;

        ELSE
            -- Clone the first box's metadata into additional box rows.
            -- package_quantity = 0 is the sentinel that prevents the hook from
            -- re-expanding these clone rows.
            v_box_id := uuid_generate_v4();
            INSERT INTO tool_boxes (
                tool_box_id,   tool_box_code,         insert_type_id,
                description,   location,              owner,
                notes,         package_quantity
            ) VALUES (
                v_box_id,      v_box_code,            v_box.insert_type_id,
                v_box.description, v_box.location,    v_box.owner,
                v_box.notes,   0
            );
        END IF;

        -- ── Cutting inserts for this box ──────────────────────────────────────
        FOR v_ins_num IN 1 .. GREATEST(COALESCE(v_it.inserts_per_box, 0), 0) LOOP
            v_insert_id   := uuid_generate_v4();
            v_insert_code := v_box_code || '-' || v_ins_num;

            INSERT INTO cutting_inserts (
                insert_id,    insert_code,   tool_box_id,
                insert_type_id, insert_number
            ) VALUES (
                v_insert_id,  v_insert_code, v_box_id,
                v_box.insert_type_id, v_ins_num
            );

            -- ── Edges for this insert ─────────────────────────────────────────
            FOR v_edge_idx IN 1 .. GREATEST(COALESCE(v_it.edge_count, 0), 0) LOOP
                INSERT INTO insert_edges (
                    edge_id,           edge_code,
                    insert_id,         edge_identifier
                ) VALUES (
                    uuid_generate_v4(),
                    v_insert_code || v_edge_letters[v_edge_idx],
                    v_insert_id,
                    v_edge_letters[v_edge_idx]
                );
            END LOOP;

        END LOOP;

    END LOOP;
END;
$$;

COMMENT ON FUNCTION expand_tool_box_intake(UUID) IS
    'Called by the Directus box-intake hook after a tool_box is created with package_quantity >= 1. '
    'Generates codes in the pattern {short_code}-{box_seq}-{insert_pos}{edge_letter} '
    'and creates all child cutting_inserts and insert_edges. '
    'Clone boxes receive package_quantity=0 to prevent recursive re-expansion.';

-- migrate:down
DROP FUNCTION IF EXISTS expand_tool_box_intake(UUID);
DROP FUNCTION IF EXISTS generate_insert_short_code(TEXT);
DROP INDEX  IF EXISTS insert_types_short_code_unique;
ALTER TABLE insert_types  DROP COLUMN IF EXISTS short_code;
ALTER TABLE tool_boxes    ALTER COLUMN tool_box_code DROP DEFAULT;
COMMENT ON COLUMN tool_boxes.package_quantity IS 'Number of inserts in the original manufacturer package.';
