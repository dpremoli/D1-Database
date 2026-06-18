-- migrate:up
-- Flattened SQL views for the LLM text-to-SQL layer and Directus display.
-- All views are prefixed v_ (spec §6). They consolidate multi-table joins into
-- single flat targets so an LLM with a limited context window can generate
-- correct SQL without needing to reason about the full join graph.
-- Views are read-only projections; all writes go through the base tables.

-- ---------------------------------------------------------------------------
-- v_complete_sample_history
-- One row per sample with denormalized material and project context.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_complete_sample_history AS
SELECT
    ps.sample_id,
    ps.sample_code,
    ps.form,
    ps.mass_grams,
    ps.diameter_mm,
    ps.length_mm,
    ps.thickness_mm,
    ps.current_status,
    ps.manufactured_date,
    ps.export_controlled,
    ps.notes,
    ps.created_at,
    ps.updated_at,
    m.alloy_code,
    m.common_name                   AS material_name,
    m.iso_code                      AS material_iso_code,
    m.density_g_per_cm3,
    p.project_code,
    p.project_name,
    p.document_number               AS project_document_number
FROM physical_samples AS ps
LEFT JOIN materials AS m ON ps.material_id = m.material_id
LEFT JOIN projects AS p ON ps.project_id = p.project_id;

COMMENT ON VIEW v_complete_sample_history
    IS 'Flat sample profile with material and project context. Primary LLM target for'
       ' sample-centric queries. Join manufacturing_operations or test_sessions for events.';

-- ---------------------------------------------------------------------------
-- v_tooling_hierarchy
-- Full three-level denormalized tooling view.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_tooling_hierarchy AS
SELECT
    tb.tool_box_id,
    tb.tool_box_code,
    tb.description                  AS tool_box_description,
    tb.location                     AS tool_box_location,
    ci.insert_id,
    ci.insert_code,
    ci.insert_number,
    ci.is_depleted                  AS insert_depleted,
    ie.edge_id,
    ie.edge_code,
    ie.edge_identifier,
    ie.is_used                      AS edge_used,
    it.type_code                    AS insert_type_code,
    it.manufacturer                 AS insert_manufacturer,
    it.substrate                    AS insert_substrate
FROM tool_boxes AS tb
LEFT JOIN cutting_inserts AS ci ON tb.tool_box_id = ci.tool_box_id
LEFT JOIN insert_edges AS ie ON ci.insert_id = ie.insert_id
LEFT JOIN insert_types AS it ON ci.insert_type_id = it.insert_type_id;

COMMENT ON VIEW v_tooling_hierarchy
    IS 'Full denormalized view of the 3-tier tooling hierarchy:'
       ' tool_boxes → cutting_inserts → insert_edges.';

-- ---------------------------------------------------------------------------
-- v_sample_genealogy_flat
-- Denormalized parent-child lineage pairs.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_sample_genealogy_flat AS
SELECT
    sg.relationship_type,
    sg.fraction,
    child_s.sample_id               AS child_sample_id,
    child_s.sample_code             AS child_sample_code,
    child_s.form                    AS child_form,
    child_s.current_status          AS child_status,
    parent_s.sample_id              AS parent_sample_id,
    parent_s.sample_code            AS parent_sample_code,
    parent_s.form                   AS parent_form
FROM sample_genealogy AS sg
INNER JOIN physical_samples AS child_s ON sg.child_sample_id = child_s.sample_id
INNER JOIN physical_samples AS parent_s ON sg.parent_sample_id = parent_s.sample_id;

COMMENT ON VIEW v_sample_genealogy_flat
    IS 'Flat parent-child lineage pairs. For forward traceability:'
       ' WHERE parent_sample_code = ''...''. For reverse: WHERE child_sample_code = ''...''.';

-- ---------------------------------------------------------------------------
-- v_manufacturing_operations_full
-- Operations with method, sample, tooling, and project context.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_manufacturing_operations_full AS
SELECT
    mo.operation_id,
    mo.pass_code,
    mo.operation_date,
    mo.operation_sequence,
    mo.operator_name,
    mo.recorded_metadata,
    mo.capture_software,
    mo.capture_frequency_khz,
    mo.file_storage_pointer,
    mo.force_file_id,
    mo.outcome_notes,
    mo.created_at,
    ps.sample_id,
    ps.sample_code,
    mm.method_id,
    mm.method_name,
    mm.method_code,
    p.project_code,
    p.project_name,
    e.equipment_code,
    e.equipment_name,
    t.tool_code,
    ie.edge_code                    AS insert_edge_code,
    ci.insert_code,
    tb.tool_box_code
FROM manufacturing_operations AS mo
INNER JOIN physical_samples AS ps ON mo.sample_id = ps.sample_id
INNER JOIN manufacturing_methods AS mm ON mo.method_id = mm.method_id
LEFT JOIN projects AS p ON mo.project_id = p.project_id
LEFT JOIN equipment AS e ON mo.equipment_id = e.equipment_id
LEFT JOIN tools AS t ON mo.tool_id = t.tool_id
LEFT JOIN insert_edges AS ie ON mo.insert_edge_id = ie.edge_id
LEFT JOIN cutting_inserts AS ci ON ie.insert_id = ci.insert_id
LEFT JOIN tool_boxes AS tb ON ci.tool_box_id = tb.tool_box_id;

COMMENT ON VIEW v_manufacturing_operations_full
    IS 'Operations with fully denormalized method, sample, tooling, and project context.'
       ' Use recorded_metadata JSONB for method-specific parameters.';

-- ---------------------------------------------------------------------------
-- v_stock_provenance
-- Which raw stock lots contributed to which samples.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_stock_provenance AS
SELECT
    ps.sample_id,
    ps.sample_code,
    rsl.lot_id,
    rsl.lot_code,
    rsl.stock_type,
    rsl.supplier_name,
    rsl.inbound_mass_grams,
    rsl.remaining_mass_grams,
    ssp.mass_used_grams,
    mat.alloy_code,
    mat.common_name                 AS material_name
FROM sample_stock_provenance AS ssp
INNER JOIN physical_samples AS ps ON ssp.sample_id = ps.sample_id
INNER JOIN raw_stock_lots AS rsl ON ssp.lot_id = rsl.lot_id
LEFT JOIN materials AS mat ON rsl.material_id = mat.material_id;

COMMENT ON VIEW v_stock_provenance
    IS 'Material provenance: which raw_stock_lots fed which physical_samples.'
       ' Enables full cradle-to-gate traceability from inbound receipt to sample.';

-- ---------------------------------------------------------------------------
-- v_test_sessions_full
-- Test sessions with sample, equipment, tooling, and project context.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_test_sessions_full AS
SELECT
    ts.session_id,
    ts.session_date,
    ts.test_type,
    ts.operator_name,
    ts.capture_software,
    ts.capture_frequency_khz,
    ts.file_storage_pointer,
    ts.file_size_gb,
    ts.status,
    ts.summary_stats,
    ts.plot_uris,
    ts.notes,
    ts.created_at,
    ps.sample_id,
    ps.sample_code,
    p.project_code,
    p.project_name,
    e.equipment_code,
    e.equipment_name,
    ie.edge_code                    AS insert_edge_code,
    ci.insert_code,
    tb.tool_box_code
FROM test_sessions AS ts
INNER JOIN physical_samples AS ps ON ts.sample_id = ps.sample_id
LEFT JOIN projects AS p ON ts.project_id = p.project_id
LEFT JOIN equipment AS e ON ts.equipment_id = e.equipment_id
LEFT JOIN insert_edges AS ie ON ts.insert_edge_id = ie.edge_id
LEFT JOIN cutting_inserts AS ci ON ie.insert_id = ci.insert_id
LEFT JOIN tool_boxes AS tb ON ci.tool_box_id = tb.tool_box_id;

COMMENT ON VIEW v_test_sessions_full
    IS 'Test sessions with fully denormalized sample, equipment, and tooling context.'
       ' plot_uris and summary_stats are populated by the async heavy-data worker.';

-- migrate:down

DROP VIEW IF EXISTS v_test_sessions_full;
DROP VIEW IF EXISTS v_stock_provenance;
DROP VIEW IF EXISTS v_manufacturing_operations_full;
DROP VIEW IF EXISTS v_sample_genealogy_flat;
DROP VIEW IF EXISTS v_tooling_hierarchy;
DROP VIEW IF EXISTS v_complete_sample_history;
