-- migrate:up
-- Replace the FRM point-cloud cap (a target count the step was derived from)
-- with a direct downsample stride: process_force.m now takes every Nth point
-- via data(1:N:end), which the admin sets explicitly instead of a target total.

ALTER TABLE force_crawler_state RENAME COLUMN frm_max_points TO frm_downsample_step;
ALTER TABLE force_crawler_state ALTER COLUMN frm_downsample_step SET DEFAULT 5;
UPDATE force_crawler_state SET frm_downsample_step = 5 WHERE frm_downsample_step > 1000;

COMMENT ON COLUMN force_crawler_state.frm_downsample_step IS
    'FRM point-cloud stride: keeps every Nth sample (data(1:N:end)) — 1 = full density, higher = sparser/faster.';

UPDATE directus_fields SET field = 'frm_downsample_step' WHERE collection = 'force_crawler_state' AND field = 'frm_max_points';

-- migrate:down
UPDATE directus_fields SET field = 'frm_max_points' WHERE collection = 'force_crawler_state' AND field = 'frm_downsample_step';
ALTER TABLE force_crawler_state ALTER COLUMN frm_downsample_step SET DEFAULT 1200000;
UPDATE force_crawler_state SET frm_downsample_step = 1200000 WHERE frm_downsample_step <= 1000;
ALTER TABLE force_crawler_state RENAME COLUMN frm_downsample_step TO frm_max_points;
