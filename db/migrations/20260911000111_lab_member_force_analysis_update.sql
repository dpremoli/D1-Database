-- migrate:up
-- Lab Member has full CRUD on manufacturing_operations already, but only READ on
-- machining_force_analysis (20260705000075_machining_force_analysis_meta.sql made that
-- read-only intentionally, before the crop-override feature existed). That means a non-admin
-- Lab Member already gets a silent 403 from the plotting dashboard's "Save crop" button
-- (crop_start_idx_override/crop_end_idx_override, added by 20260828000103_force_crop_override.sql)
-- and from the inner/outer diameter overrides — the new combined "Save changes" dialog
-- (metadata + crop, one write) makes that failure far more visible than the crop-only button did.
-- Grant UPDATE only (not create/delete — rows are created by the host orchestrator, not the
-- plotting UI), fields='*' to match every other Lab Member permission in this schema.

INSERT INTO directus_permissions (policy, collection, action, permissions, validation, fields)
SELECT '20000002-0000-0000-0000-000000000002', 'machining_force_analysis', 'update', '{}', '{}', '*'
WHERE NOT EXISTS (
    SELECT 1 FROM directus_permissions p
    WHERE p.policy = '20000002-0000-0000-0000-000000000002'
      AND p.collection = 'machining_force_analysis' AND p.action = 'update'
);

-- migrate:down
DELETE FROM directus_permissions
WHERE policy = '20000002-0000-0000-0000-000000000002'
  AND collection = 'machining_force_analysis' AND action = 'update';
