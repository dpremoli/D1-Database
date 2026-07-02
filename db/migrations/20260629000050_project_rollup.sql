-- migrate:up
-- Read-only project rollup: everything that belongs to a project transitively, derived
-- live (no denormalised FKs). An operation belongs to a project directly (project_id) OR
-- via its campaign (campaign.project_id). Tooling/samples/materials/equipment are surfaced
-- as "used in this project" — NOT ownership, just provenance for traceability.
CREATE VIEW v_project_rollup AS
WITH ops AS (
    SELECT o.*, COALESCE(o.project_id, c.project_id) AS proj
    FROM manufacturing_operations o
    LEFT JOIN campaigns c ON c.campaign_id = o.campaign_id
    WHERE COALESCE(o.project_id, c.project_id) IS NOT NULL
)
SELECT md5('operation:' || operation_id::text) AS row_id, proj AS project_id,
       'operation'::text AS kind, pass_code AS code,
       machining_operation_subtype AS detail, campaign_id
FROM ops
UNION ALL
SELECT DISTINCT md5('tool:' || proj::text || ':' || t.tool_id::text), proj,
       'tool', t.tool_code, t.tool_name, NULL::uuid
FROM ops JOIN tools t ON t.tool_id = ops.tool_id
UNION ALL
SELECT DISTINCT md5('edge:' || proj::text || ':' || e.edge_id::text), proj,
       'insert_edge', e.edge_code, NULL, NULL::uuid
FROM ops JOIN insert_edges e ON e.edge_id = ops.insert_edge_id
UNION ALL
SELECT DISTINCT md5('insert:' || proj::text || ':' || ci.insert_id::text), proj,
       'cutting_insert', ci.insert_code, NULL, NULL::uuid
FROM ops JOIN insert_edges e ON e.edge_id = ops.insert_edge_id
         JOIN cutting_inserts ci ON ci.insert_id = e.insert_id
UNION ALL
SELECT DISTINCT md5('sample:' || proj::text || ':' || s.sample_id::text), proj,
       'sample', s.sample_code, s.nickname, NULL::uuid
FROM ops JOIN physical_samples s ON s.sample_id = ops.sample_id
UNION ALL
SELECT DISTINCT md5('material:' || proj::text || ':' || m.material_id::text), proj,
       'material', m.alloy_code, m.common_name, NULL::uuid
FROM ops JOIN materials m ON m.material_id = ops.material_id
UNION ALL
SELECT DISTINCT md5('equipment:' || proj::text || ':' || eq.equipment_id::text), proj,
       'equipment', eq.equipment_code, eq.equipment_name, NULL::uuid
FROM ops JOIN equipment eq ON eq.equipment_id = ops.equipment_id;

COMMENT ON VIEW v_project_rollup
    IS 'Live read-only rollup of a project: operations (direct + via campaign) and the distinct tooling/samples/materials/equipment used. Provenance, not ownership.';

-- migrate:down
DROP VIEW IF EXISTS v_project_rollup;
