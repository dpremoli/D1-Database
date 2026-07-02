-- migrate:up
-- Fill schema gaps identified by comparing AppSheet export columns
-- against the current table definitions.

-- ── physical_samples ─────────────────────────────────────────────────────────
ALTER TABLE physical_samples
    ADD COLUMN IF NOT EXISTS width_mm           NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS owner              TEXT,
    ADD COLUMN IF NOT EXISTS co_owners          TEXT,
    ADD COLUMN IF NOT EXISTS manufacturing_route TEXT,
    ADD COLUMN IF NOT EXISTS mounted            BOOLEAN,
    ADD COLUMN IF NOT EXISTS mounting_method    TEXT;

COMMENT ON COLUMN physical_samples.width_mm            IS 'Width in millimetres (x dimension), if applicable.';
COMMENT ON COLUMN physical_samples.owner               IS 'Primary owner / responsible person for this sample.';
COMMENT ON COLUMN physical_samples.co_owners           IS 'Comma-separated list of co-owners.';
COMMENT ON COLUMN physical_samples.manufacturing_route IS 'Free-text manufacturing route label from legacy AppSheet (e.g. FAST, Rolled, Cast).';
COMMENT ON COLUMN physical_samples.mounted             IS 'TRUE if the sample has been mounted in resin or a holder.';
COMMENT ON COLUMN physical_samples.mounting_method     IS 'Mounting method used, e.g. Hot Press, Cold Mount.';

-- ── alloying_elements ────────────────────────────────────────────────────────
ALTER TABLE alloying_elements
    ADD COLUMN IF NOT EXISTS atomic_weight      NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS density_g_per_cm3  NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS melting_point_k    NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS boiling_point_k    NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS electronegativity  NUMERIC(6,3),
    ADD COLUMN IF NOT EXISTS atomic_radius_pm   NUMERIC(8,2);

COMMENT ON COLUMN alloying_elements.atomic_weight     IS 'Standard atomic weight (g/mol).';
COMMENT ON COLUMN alloying_elements.density_g_per_cm3 IS 'Elemental density at STP (g/cm³).';
COMMENT ON COLUMN alloying_elements.melting_point_k   IS 'Melting point in Kelvin.';
COMMENT ON COLUMN alloying_elements.boiling_point_k   IS 'Boiling point in Kelvin.';
COMMENT ON COLUMN alloying_elements.electronegativity IS 'Pauling electronegativity.';
COMMENT ON COLUMN alloying_elements.atomic_radius_pm  IS 'Atomic radius in picometres.';

-- ── insert_types ─────────────────────────────────────────────────────────────
ALTER TABLE insert_types
    ADD COLUMN IF NOT EXISTS op_type                  TEXT,
    ADD COLUMN IF NOT EXISTS mounting_style_code      TEXT,
    ADD COLUMN IF NOT EXISTS inserts_per_box          INTEGER,
    ADD COLUMN IF NOT EXISTS edge_count               INTEGER,
    ADD COLUMN IF NOT EXISTS nose_radius_mm           NUMERIC(8,3),
    ADD COLUMN IF NOT EXISTS cutting_edge_length_mm   NUMERIC(8,3),
    ADD COLUMN IF NOT EXISTS included_angle_deg       NUMERIC(8,3),
    ADD COLUMN IF NOT EXISTS fixing_hole_diameter_mm  NUMERIC(8,3),
    ADD COLUMN IF NOT EXISTS material_class           TEXT;

COMMENT ON COLUMN insert_types.op_type                 IS 'Primary operation type, e.g. Roughing, Finishing, Semi-Finishing.';
COMMENT ON COLUMN insert_types.mounting_style_code     IS 'Insert fixing/clamping style code (IFS), e.g. P, M, S.';
COMMENT ON COLUMN insert_types.inserts_per_box         IS 'Standard box quantity from manufacturer.';
COMMENT ON COLUMN insert_types.edge_count              IS 'Number of usable cutting edges per insert.';
COMMENT ON COLUMN insert_types.nose_radius_mm          IS 'Corner/nose radius RE in millimetres.';
COMMENT ON COLUMN insert_types.cutting_edge_length_mm  IS 'Cutting edge length L in millimetres.';
COMMENT ON COLUMN insert_types.included_angle_deg      IS 'Included/relief angle ESPR in degrees.';
COMMENT ON COLUMN insert_types.fixing_hole_diameter_mm IS 'Fixing hole diameter in millimetres, if applicable.';
COMMENT ON COLUMN insert_types.material_class          IS 'ISO 513 TMC1 material classification code, e.g. P, M, K, S.';

-- ── tools ────────────────────────────────────────────────────────────────────
ALTER TABLE tools
    ADD COLUMN IF NOT EXISTS manufacturer           TEXT,
    ADD COLUMN IF NOT EXISTS datasheet_url          TEXT,
    ADD COLUMN IF NOT EXISTS op_type                TEXT,
    ADD COLUMN IF NOT EXISTS cutter_diameter_mm     NUMERIC(8,3),
    ADD COLUMN IF NOT EXISTS shank_width_mm         NUMERIC(8,3),
    ADD COLUMN IF NOT EXISTS shank_length_mm        NUMERIC(8,3),
    ADD COLUMN IF NOT EXISTS overall_length_mm      NUMERIC(8,3),
    ADD COLUMN IF NOT EXISTS shank_type             TEXT,
    ADD COLUMN IF NOT EXISTS cutting_direction      TEXT,
    ADD COLUMN IF NOT EXISTS insert_clamping_system TEXT;

COMMENT ON COLUMN tools.manufacturer            IS 'Tool holder manufacturer name.';
COMMENT ON COLUMN tools.datasheet_url           IS 'Link to manufacturer datasheet or product page.';
COMMENT ON COLUMN tools.op_type                 IS 'Operation type, e.g. External, Internal, Face.';
COMMENT ON COLUMN tools.cutter_diameter_mm      IS 'Cutter/body diameter in millimetres.';
COMMENT ON COLUMN tools.shank_width_mm          IS 'Shank width B in millimetres.';
COMMENT ON COLUMN tools.shank_length_mm         IS 'Shank length in millimetres.';
COMMENT ON COLUMN tools.overall_length_mm       IS 'Overall tool length in millimetres.';
COMMENT ON COLUMN tools.shank_type              IS 'Shank interface type, e.g. Capto, HSK, ISO.';
COMMENT ON COLUMN tools.cutting_direction       IS 'Cutting direction: Right-Hand, Left-Hand, Neutral.';
COMMENT ON COLUMN tools.insert_clamping_system  IS 'Insert clamping system code, e.g. P-clamp, S-clamp.';

-- ── equipment ────────────────────────────────────────────────────────────────
ALTER TABLE equipment
    ADD COLUMN IF NOT EXISTS manufacturer TEXT;

COMMENT ON COLUMN equipment.manufacturer IS 'Machine/equipment manufacturer name.';

-- ── cutting_inserts ──────────────────────────────────────────────────────────
ALTER TABLE cutting_inserts
    ADD COLUMN IF NOT EXISTS location TEXT,
    ADD COLUMN IF NOT EXISTS owner    TEXT;

COMMENT ON COLUMN cutting_inserts.location IS 'Physical storage location of this insert.';
COMMENT ON COLUMN cutting_inserts.owner    IS 'Owner / responsible person for this insert.';

-- ── tool_boxes ───────────────────────────────────────────────────────────────
ALTER TABLE tool_boxes
    ADD COLUMN IF NOT EXISTS package_quantity INTEGER,
    ADD COLUMN IF NOT EXISTS owner            TEXT;

COMMENT ON COLUMN tool_boxes.package_quantity IS 'Number of inserts in the original manufacturer package.';
COMMENT ON COLUMN tool_boxes.owner            IS 'Owner / responsible person for this box.';

-- migrate:down
ALTER TABLE physical_samples   DROP COLUMN IF EXISTS width_mm, DROP COLUMN IF EXISTS owner, DROP COLUMN IF EXISTS co_owners, DROP COLUMN IF EXISTS manufacturing_route, DROP COLUMN IF EXISTS mounted, DROP COLUMN IF EXISTS mounting_method;
ALTER TABLE alloying_elements  DROP COLUMN IF EXISTS atomic_weight, DROP COLUMN IF EXISTS density_g_per_cm3, DROP COLUMN IF EXISTS melting_point_k, DROP COLUMN IF EXISTS boiling_point_k, DROP COLUMN IF EXISTS electronegativity, DROP COLUMN IF EXISTS atomic_radius_pm;
ALTER TABLE insert_types       DROP COLUMN IF EXISTS op_type, DROP COLUMN IF EXISTS mounting_style_code, DROP COLUMN IF EXISTS inserts_per_box, DROP COLUMN IF EXISTS edge_count, DROP COLUMN IF EXISTS nose_radius_mm, DROP COLUMN IF EXISTS cutting_edge_length_mm, DROP COLUMN IF EXISTS included_angle_deg, DROP COLUMN IF EXISTS fixing_hole_diameter_mm, DROP COLUMN IF EXISTS material_class;
ALTER TABLE tools              DROP COLUMN IF EXISTS manufacturer, DROP COLUMN IF EXISTS datasheet_url, DROP COLUMN IF EXISTS op_type, DROP COLUMN IF EXISTS cutter_diameter_mm, DROP COLUMN IF EXISTS shank_width_mm, DROP COLUMN IF EXISTS shank_length_mm, DROP COLUMN IF EXISTS overall_length_mm, DROP COLUMN IF EXISTS shank_type, DROP COLUMN IF EXISTS cutting_direction, DROP COLUMN IF EXISTS insert_clamping_system;
ALTER TABLE equipment          DROP COLUMN IF EXISTS manufacturer;
ALTER TABLE cutting_inserts    DROP COLUMN IF EXISTS location, DROP COLUMN IF EXISTS owner;
ALTER TABLE tool_boxes         DROP COLUMN IF EXISTS package_quantity, DROP COLUMN IF EXISTS owner;
