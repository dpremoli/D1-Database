import { describe, expect, it } from 'vitest';
import {
	DEFAULT_RECIPE, STEP_META, recipeChannels, recipesEquivalent, type Recipe,
} from './recipeChannels';

const clone = (r: Recipe): Recipe => JSON.parse(JSON.stringify(r));

describe('DEFAULT_RECIPE', () => {
	it('matches scripts/diag/recipe.py — op order, ids, envelope off', () => {
		expect(DEFAULT_RECIPE.steps.map((s) => s.op)).toEqual([
			'frame_transform', 'angular_resample', 'tsa', 'radial_detrend',
			'getis_ord', 'hdbscan', 'envelope',
		]);
		expect(DEFAULT_RECIPE.steps.map((s) => s.id)).toEqual(['s1', 's2', 's3', 's4', 's5', 's6', 's7']);
		expect(DEFAULT_RECIPE.steps.find((s) => s.op === 'envelope')!.on).toBe(false);
	});

	it('every step op has STEP_META', () => {
		for (const s of DEFAULT_RECIPE.steps) expect(STEP_META[s.op]).toBeDefined();
	});
});

describe('recipeChannels', () => {
	it('flags every channel produced by an enabled step', () => {
		const chans = recipeChannels(DEFAULT_RECIPE);
		const produced = new Set(chans.filter((c) => c.produced).map((c) => c.key));
		// tsa + radial_detrend + getis_ord + hdbscan enabled; envelope off.
		expect(produced).toEqual(new Set(['residZ', 'giStar', 'giSig', 'clusterId', 'glosh', 'tsaResid']));
		expect(chans.find((c) => c.key === 'envBand')!.produced).toBe(false);
	});

	it('disabling hdbscan removes its channels', () => {
		const r = clone(DEFAULT_RECIPE);
		r.steps.find((s) => s.op === 'hdbscan')!.on = false;
		const chans = recipeChannels(r);
		expect(chans.find((c) => c.key === 'clusterId')!.produced).toBe(false);
		expect(chans.find((c) => c.key === 'glosh')!.produced).toBe(false);
		expect(chans.find((c) => c.key === 'residZ')!.produced).toBe(true);
	});
});

describe('recipesEquivalent', () => {
	it('true for a clone', () => {
		expect(recipesEquivalent(DEFAULT_RECIPE, clone(DEFAULT_RECIPE))).toBe(true);
	});

	it('false when an enabled param changes', () => {
		const r = clone(DEFAULT_RECIPE);
		r.steps.find((s) => s.op === 'getis_ord')!.params.k = 50;
		expect(recipesEquivalent(DEFAULT_RECIPE, r)).toBe(false);
	});

	it('true when only a DISABLED step param changes', () => {
		const r = clone(DEFAULT_RECIPE);
		r.steps.find((s) => s.op === 'envelope')!.params.bandwidth_frac = 0.4;
		expect(recipesEquivalent(DEFAULT_RECIPE, r)).toBe(true);
	});

	it('false when a step is enabled', () => {
		const r = clone(DEFAULT_RECIPE);
		r.steps.find((s) => s.op === 'envelope')!.on = true;
		expect(recipesEquivalent(DEFAULT_RECIPE, r)).toBe(false);
	});
});
