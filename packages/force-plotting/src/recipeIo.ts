// JSON import / export of diagnostics recipes, and the "modified since loaded" check behind the
// library badge. Pure: no host, no DOM. Import validates the file shape and the recipe itself
// (known ops, typed params, satisfiable step order via recipeProblems) so a bad file is refused
// with a reason instead of being stored and failing later in the host bake.
import { recipeProblems, recipesEquivalent, STEP_META, type Recipe, type RecipeStep } from './recipeChannels';

export const RECIPE_FILE_TAG = 1;

export interface RecipeFile {
	d1_recipe: number;
	name: string;
	notes: string | null;
	recipe: Recipe;
}

export type ParsedRecipe =
	| { ok: true; name: string; notes: string | null; recipe: Recipe }
	| { ok: false; error: string };

export function exportRecipeJson(p: { name: string; notes?: string | null; recipe: Recipe }): string {
	const file: RecipeFile = { d1_recipe: RECIPE_FILE_TAG, name: p.name, notes: p.notes ?? null, recipe: p.recipe };
	return JSON.stringify(file, null, 2);
}

/** A filesystem-safe name for the downloaded file. */
export function recipeFileName(name: string): string {
	const base = name.trim().replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^_+|_+$/g, '');
	return `${base || 'recipe'}.d1recipe.json`;
}

function isObj(v: unknown): v is Record<string, unknown> {
	return !!v && typeof v === 'object' && !Array.isArray(v);
}

function checkStep(s: unknown, i: number, seen: Set<string>): string | null {
	if (!isObj(s)) return `step ${i + 1} is not an object`;
	if (typeof s.id !== 'string' || !s.id) return `step ${i + 1} has no id`;
	if (seen.has(s.id)) return `step id "${s.id}" is used twice`;
	seen.add(s.id);
	if (typeof s.op !== 'string' || !STEP_META[s.op]) return `step ${i + 1} has an unknown op "${String(s.op)}"`;
	if (typeof s.on !== 'boolean') return `step "${s.id}" needs on: true or false`;
	if (!isObj(s.params)) return `step "${s.id}" has no params object`;
	for (const [k, v] of Object.entries(s.params)) {
		if (!(v === null || typeof v === 'number' || typeof v === 'string')) {
			return `step "${s.id}" param "${k}" must be a number, string or null`;
		}
		if (typeof v === 'number' && !Number.isFinite(v)) return `step "${s.id}" param "${k}" is not finite`;
	}
	if (s.inputs !== undefined && !isObj(s.inputs)) return `step "${s.id}" inputs must be an object`;
	return null;
}

/** Validate a recipe document on its own (also used for a bare recipe in an import file). */
export function validateRecipe(r: unknown): string | null {
	if (!isObj(r)) return 'recipe is not an object';
	if (typeof r.recipe_version !== 'number') return 'recipe_version missing';
	if (typeof r.name !== 'string') return 'recipe name missing';
	if (!Array.isArray(r.steps) || r.steps.length === 0) return 'recipe has no steps';
	const seen = new Set<string>();
	for (let i = 0; i < r.steps.length; i++) {
		const e = checkStep(r.steps[i], i, seen);
		if (e) return e;
	}
	const problems = recipeProblems(r as unknown as Recipe);
	if (problems.length) return problems[0].message;
	return null;
}

export function parseRecipeJson(text: string): ParsedRecipe {
	let doc: unknown;
	try { doc = JSON.parse(text); } catch { return { ok: false, error: 'not valid JSON' }; }
	if (!isObj(doc)) return { ok: false, error: 'not a recipe file' };
	// Accept either the wrapped export or a bare recipe document.
	const wrapped = doc.d1_recipe !== undefined;
	if (wrapped && doc.d1_recipe !== RECIPE_FILE_TAG) {
		return { ok: false, error: `unsupported recipe file version ${String(doc.d1_recipe)}` };
	}
	const recipe = (wrapped ? doc.recipe : doc) as unknown;
	const err = validateRecipe(recipe);
	if (err) return { ok: false, error: err };
	const r = recipe as Recipe;
	const name = wrapped && typeof doc.name === 'string' && doc.name.trim() ? doc.name.trim() : r.name;
	const notes = wrapped && typeof doc.notes === 'string' && doc.notes ? doc.notes : null;
	const steps: RecipeStep[] = r.steps.map((s) => ({
		id: s.id, op: s.op, on: s.on, params: { ...s.params }, ...(s.inputs ? { inputs: { ...s.inputs } } : {}),
	}));
	return { ok: true, name, notes, recipe: { recipe_version: r.recipe_version, name: r.name, steps } };
}

/** "Modified since loaded": the working recipe no longer matches the library recipe it was
 *  loaded from (or last saved as). False when nothing has been loaded. */
export function isModifiedSinceLoaded(current: Recipe, loaded: Recipe | null): boolean {
	if (!loaded) return false;
	return !recipesEquivalent(current, loaded);
}
