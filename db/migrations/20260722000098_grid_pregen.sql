-- migrate:up
-- Optional crawler pre-generation of the interpolated-grid octree for big ops (mirrors the
-- raw-octree pre-gen). Off by default because a grid build is heavier than a raw octree and
-- doubles the crawl's build work; an admin opts in on the Force Crawler page. When on, each
-- discover pass enqueues a grid build for every done op above octree_threshold that has a raw
-- octree but no grid yet.
ALTER TABLE force_crawler_state
    ADD COLUMN IF NOT EXISTS grid_pregen boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN force_crawler_state.grid_pregen IS
    'Pre-build the interpolated-grid octree during the crawl for ops above octree_threshold (heavier; off by default).';

INSERT INTO directus_fields (collection, field, interface, display, options, width, sort, readonly, hidden)
SELECT 'force_crawler_state', 'grid_pregen', 'boolean', 'boolean', NULL, 'half', 15, false, false
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = 'force_crawler_state' AND f.field = 'grid_pregen'
);

-- migrate:down
DELETE FROM directus_fields WHERE collection = 'force_crawler_state' AND field = 'grid_pregen';
ALTER TABLE force_crawler_state DROP COLUMN IF EXISTS grid_pregen;
