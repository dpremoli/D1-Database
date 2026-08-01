-- migrate:up
-- Sample's primary manufacturing method, used (with alloy + date) to build the
-- sample code live: <sequence>-<alloy_code>-<method_code>-<Y>-<M>-<D>
-- (e.g. 140-IN18-MF-2026-6-21). No hard FK constraints needed beyond the method.

ALTER TABLE physical_samples
    ADD COLUMN IF NOT EXISTS primary_method_id UUID
        REFERENCES manufacturing_methods(method_id) ON DELETE SET NULL;

COMMENT ON COLUMN physical_samples.primary_method_id IS
    'Primary manufacturing method that produced this sample; its method_code is used in the generated sample code.';

-- migrate:down
ALTER TABLE physical_samples DROP COLUMN IF EXISTS primary_method_id;
