-- migrate:up
-- The diagnostics pipeline becomes an editable recipe rather than a fixed sequence
-- (docs/superpowers/specs/2026-09-01-diagnostics-recipe-workbench-design.md). Mirrors the
-- filter_chain / filter_profiles pair exactly: a per-cut active document plus a named,
-- reusable library, where applying a library entry copies its document onto the cut.
ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS diag_recipe      jsonb,
    ADD COLUMN IF NOT EXISTS diag_recipe_hash text;

COMMENT ON COLUMN machining_force_analysis.diag_recipe IS
    'The recipe this cut''s diagnostics were built from. NULL means the built-in default (scripts/diag/recipe.py DEFAULT_RECIPE).';
COMMENT ON COLUMN machining_force_analysis.diag_recipe_hash IS
    'Identity of the recipe the CURRENT diag artifacts were baked from. Staleness has two independent axes: diag_version tracks code changes, this tracks configuration changes. A baked artifact is reusable only when both match.';

CREATE TABLE IF NOT EXISTS diag_recipes (
    recipe_id   UUID        NOT NULL DEFAULT uuid_generate_v4(),
    name        VARCHAR(128) NOT NULL,
    recipe      JSONB       NOT NULL,
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT diag_recipes_pkey PRIMARY KEY (recipe_id),
    CONSTRAINT diag_recipes_name_unique UNIQUE (name)
);

COMMENT ON TABLE diag_recipes IS
    'Named diagnostics recipe library; applying one copies its document onto machining_force_analysis.diag_recipe.';

-- migrate:down
DROP TABLE IF EXISTS diag_recipes;
ALTER TABLE machining_force_analysis
    DROP COLUMN IF EXISTS diag_recipe,
    DROP COLUMN IF EXISTS diag_recipe_hash;
