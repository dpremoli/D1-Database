import { describe, expect, it } from 'vitest';
import {
	DEFAULT_RECIPE, STEP_META, recipeChannels, recipeProblems, recipesEquivalent, type Recipe,
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

describe('recipeProblems', () => {
	const off = (op: string): Recipe => ({
		...DEFAULT_RECIPE,
		steps: DEFAULT_RECIPE.steps.map((s) => (s.op === op ? { ...s, on: false } : s)),
	});

	it('accepts the default recipe', () => {
		expect(recipeProblems(DEFAULT_RECIPE)).toEqual([]);
	});

	it('flags the step the service would 422 on, naming the fix in step labels', () => {
		// The exact field failure: radial_detrend off -> getis_ord (s5) has no resid_z.
		const probs = recipeProblems(off('radial_detrend'));
		expect(probs.length).toBeGreaterThan(0);
		expect(probs[0].stepId).toBe('s5');
		expect(probs[0].missing).toContain('resid_z');
		expect(probs[0].message).toContain('Radial detrend');
	});

	it('does not cascade a broken step into a false second failure', () => {
		// tsa off breaks radial_detrend; getis_ord then also lacks resid_z, so both are
		// genuinely broken -- but each must be reported against its own missing column.
		const probs = recipeProblems(off('tsa'));
		expect(probs.map((p) => p.stepId)).toEqual(['s4', 's5', 's6']);
		expect(probs[0].missing).toContain('tsa_resid');
		expect(probs[1].missing).toContain('resid_z');
	});

	it('accepts a recipe whose broken consumer is also switched off', () => {
		const r: Recipe = {
			...DEFAULT_RECIPE,
			steps: DEFAULT_RECIPE.steps.map((s) =>
				['radial_detrend', 'getis_ord', 'hdbscan'].includes(s.op) ? { ...s, on: false } : s),
		};
		expect(recipeProblems(r)).toEqual([]);
	});
});
