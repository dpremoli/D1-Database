import { describe, expect, it } from 'vitest';
import { DEFAULT_RECIPE, type Recipe } from './recipeChannels';
import {
	exportRecipeJson, isModifiedSinceLoaded, parseRecipeJson, recipeFileName, validateRecipe,
} from './recipeIo';

const clone = (r: Recipe): Recipe => JSON.parse(JSON.stringify(r));

describe('recipe import / export', () => {
	it('round-trips an export', () => {
		const out = parseRecipeJson(exportRecipeJson({ name: 'Camp A', notes: 'n', recipe: DEFAULT_RECIPE }));
		expect(out).toMatchObject({ ok: true, name: 'Camp A', notes: 'n' });
		if (out.ok) expect(out.recipe).toEqual(DEFAULT_RECIPE);
	});
	it('accepts a bare recipe and takes its name', () => {
		const out = parseRecipeJson(JSON.stringify(DEFAULT_RECIPE));
		expect(out).toMatchObject({ ok: true, name: 'Default', notes: null });
	});
	it('refuses non-JSON, wrong version and non-objects', () => {
		expect(parseRecipeJson('{nope')).toEqual({ ok: false, error: 'not valid JSON' });
		expect(parseRecipeJson('[1]').ok).toBe(false);
		expect(parseRecipeJson(JSON.stringify({ d1_recipe: 9, recipe: DEFAULT_RECIPE }))).toMatchObject({ ok: false });
	});
	it('refuses unknown ops, bad params, duplicate ids and empty recipes', () => {
		const r = clone(DEFAULT_RECIPE);
		r.steps[0].op = 'rm_rf';
		expect(validateRecipe(r)).toMatch(/unknown op/);
		const p = clone(DEFAULT_RECIPE);
		(p.steps[1].params as Record<string, unknown>).samples_per_rev = { x: 1 };
		expect(validateRecipe(p)).toMatch(/param/);
		const d = clone(DEFAULT_RECIPE);
		d.steps[1].id = 's1';
		expect(validateRecipe(d)).toMatch(/twice/);
		expect(validateRecipe({ ...DEFAULT_RECIPE, steps: [] })).toMatch(/no steps/);
	});
	it('refuses an unsatisfiable step order (reuses recipeProblems)', () => {
		const r = clone(DEFAULT_RECIPE);
		r.steps[3].on = false; // radial_detrend off, getis_ord still needs resid_z
		expect(validateRecipe(r)).toMatch(/needs/);
	});
	it('makes a safe file name', () => {
		expect(recipeFileName(' Camp A/ 1 ')).toBe('Camp_A_1.d1recipe.json');
		expect(recipeFileName('///')).toBe('recipe.d1recipe.json');
	});
});

describe('isModifiedSinceLoaded', () => {
	it('is false with nothing loaded or an equivalent recipe', () => {
		expect(isModifiedSinceLoaded(DEFAULT_RECIPE, null)).toBe(false);
		const r = clone(DEFAULT_RECIPE);
		r.name = 'renamed';
		r.steps[0].id = 'zz';
		expect(isModifiedSinceLoaded(r, DEFAULT_RECIPE)).toBe(false);
	});
	it('is true when a param or enabled step changes', () => {
		const r = clone(DEFAULT_RECIPE);
		r.steps[4].params.k = 31;
		expect(isModifiedSinceLoaded(r, DEFAULT_RECIPE)).toBe(true);
		const e = clone(DEFAULT_RECIPE);
		e.steps[6].on = true;
		expect(isModifiedSinceLoaded(e, DEFAULT_RECIPE)).toBe(true);
	});
});
