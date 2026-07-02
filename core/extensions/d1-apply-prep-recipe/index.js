// Directus hook: d1-apply-prep-recipe
//
// The hybrid sample-prep model: a recipe is a reusable template of steps. When a
// Sample Preparation operation is created (or updated) with `source_recipe_id`
// set and it has no prep_steps yet, copy the recipe's steps into its own
// prep_steps. The copies are independent rows, so the user can then edit them
// per sample without touching the shared recipe.

const STEP_COLS = [
  'step_order', 'step_type', 'grit', 'suspension_um', 'cloth', 'etchant_id',
  'duration_s', 'force_n', 'rpm', 'temperature_c', 'lubricant', 'resin_type', 'notes',
];

export default ({ action }, { database }) => {
  const copyRecipe = async (operationId, recipeId) => {
    if (!operationId || !recipeId) return;
    // Don't clobber existing steps.
    const existing = await database('prep_steps').where({ operation_id: operationId }).first();
    if (existing) return;

    const steps = await database('prep_recipe_steps')
      .where({ recipe_id: recipeId })
      .orderBy('step_order');
    if (!steps.length) return;

    const rows = steps.map((s) => {
      const r = { operation_id: operationId };
      for (const c of STEP_COLS) r[c] = s[c];
      return r;
    });
    await database('prep_steps').insert(rows);
  };

  action('manufacturing_operations.items.create', async (meta) => {
    await copyRecipe(meta?.key, meta?.payload?.source_recipe_id);
  });

  action('manufacturing_operations.items.update', async (meta) => {
    if (meta?.payload?.source_recipe_id == null) return;
    const keys = meta?.keys || (meta?.key ? [meta.key] : []);
    for (const k of keys) await copyRecipe(k, meta.payload.source_recipe_id);
  });
};
