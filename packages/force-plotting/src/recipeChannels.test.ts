import { describe, expect, it } from 'vitest';
import {
	DEFAULT_RECIPE, STEP_META, firstDerivedIndex, primaryChannelForOp, recipeChannels,
	recipeProblems, recipesEquivalent, stepIsRevertable, type Recipe,
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

describe('primaryChannelForOp', () => {
	it('maps a step to the channel its first produced column corresponds to', () => {
		expect(primaryChannelForOp('radial_detrend')).toBe('residZ');
		expect(primaryChannelForOp('getis_ord')).toBe('giStar');
		expect(primaryChannelForOp('hdbscan')).toBe('clusterId');
		expect(primaryChannelForOp('griddify')).toBe('gridFill');
		expect(primaryChannelForOp('gmm_segmentation')).toBe('gmmId');
	});

	it('is null for a step whose products are intermediates with no channel', () => {
		expect(primaryChannelForOp('frame_transform')).toBeNull();
		expect(primaryChannelForOp('angular_resample')).toBeNull();
	});

	it('is null for an unknown op', () => {
		expect(primaryChannelForOp('not_a_real_op')).toBeNull();
	});
});

describe('firstDerivedIndex / stepIsRevertable', () => {
	it('DEFAULT_RECIPE resumes at index 2 (tsa), after frame_transform + angular_resample', () => {
		expect(firstDerivedIndex(DEFAULT_RECIPE)).toBe(2);
	});

	it('a base-tier step (frame_transform, angular_resample) is not revertable', () => {
		expect(stepIsRevertable(DEFAULT_RECIPE, 0)).toBe(false);
		expect(stepIsRevertable(DEFAULT_RECIPE, 1)).toBe(false);
	});

	it('a derived-tier step, and everything after the first derived step, is revertable', () => {
		expect(stepIsRevertable(DEFAULT_RECIPE, 2)).toBe(true);   // tsa
		expect(stepIsRevertable(DEFAULT_RECIPE, 4)).toBe(true);   // getis_ord
		expect(stepIsRevertable(DEFAULT_RECIPE, 6)).toBe(true);   // envelope (base-tier, but AFTER from_step)
	});

	it('reordering the recipe moves the boundary, not just the position', () => {
		// Drag radial_detrend (derived) to the very front: it is now index 0, and IS the
		// first derived step, so it -- and everything after it -- becomes revertable.
		const r = clone(DEFAULT_RECIPE);
		const [moved] = r.steps.splice(3, 1);   // radial_detrend
		r.steps.unshift(moved);
		expect(r.steps[0].op).toBe('radial_detrend');
		expect(firstDerivedIndex(r)).toBe(0);
		expect(stepIsRevertable(r, 0)).toBe(true);
	});

	it('no derived step at all: nothing is revertable', () => {
		const r: Recipe = { recipe_version: 1, name: 'bare', steps: [DEFAULT_RECIPE.steps[0]] };
		expect(firstDerivedIndex(r)).toBe(-1);
		expect(stepIsRevertable(r, 0)).toBe(false);
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

	// invert's dependency is params.source, a runtime choice STEP_REQUIRES cannot express
	// (scripts/diag/ops.py::_op_invert raises the matching check server-side) -- these pin
	// the client-side mirror in recipeProblems() that catches it before the request is sent.
	describe('invert (runtime source dependency)', () => {
		function withInvert(source: string, extra: Partial<Recipe> = {}): Recipe {
			return {
				...DEFAULT_RECIPE,
				...extra,
				steps: [
					...DEFAULT_RECIPE.steps,
					{ id: 'x1', op: 'invert', on: true, params: { source, mode: 'complement' } },
				],
			};
		}

		it('accepts inverting a channel an earlier enabled step produces', () => {
			expect(recipeProblems(withInvert('resid_z'))).toEqual([]);
		});

		it('flags inverting a channel nothing enabled has produced yet', () => {
			const probs = recipeProblems(withInvert('env_band'));
			expect(probs).toHaveLength(1);
			expect(probs[0].stepId).toBe('x1');
			expect(probs[0].missing).toEqual(['env_band']);
			expect(probs[0].message).toContain('Envelope band');
		});

		it('defaults the source to resid_z when the param is absent', () => {
			const r: Recipe = {
				...DEFAULT_RECIPE,
				steps: [...DEFAULT_RECIPE.steps, { id: 'x1', op: 'invert', on: true, params: {} }],
			};
			expect(recipeProblems(r)).toEqual([]);
		});

		it('does not flag a disabled invert step', () => {
			const r = withInvert('env_band');
			r.steps[r.steps.length - 1].on = false;
			expect(recipeProblems(r)).toEqual([]);
		});

		it('unblocks once the producing step is re-enabled', () => {
			const r = withInvert('env_band');
			r.steps.find((s) => s.op === 'envelope')!.on = true;
			expect(recipeProblems(r)).toEqual([]);
		});
	});
});
