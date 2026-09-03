import { describe, expect, it, vi, beforeEach } from 'vitest';
import { setForceHost, resetForceHost, type ForceHost } from './host';
import { saveRecipe, fetchRecipeLibrary } from './diagRecipes';
import { DEFAULT_RECIPE } from './recipeChannels';

const post = vi.fn();
const get = vi.fn();

beforeEach(() => {
	resetForceHost();
	setForceHost({ api: { post, get } as unknown as ForceHost['api'] } as ForceHost);
	post.mockReset().mockResolvedValue({
		data: { data: { recipe_id: '1', name: 'x', recipe: DEFAULT_RECIPE, notes: null } },
	});
	get.mockReset().mockResolvedValue({ data: { data: [] } });
});

describe('diagRecipes', () => {
	it('saveRecipe posts name / recipe / notes', async () => {
		await saveRecipe({ name: 'Campaign A', recipe: DEFAULT_RECIPE });
		expect(post).toHaveBeenCalledWith(
			'/items/diag_recipes',
			{ name: 'Campaign A', recipe: DEFAULT_RECIPE, notes: null },
			expect.anything(),
		);
	});

	it('fetchRecipeLibrary returns the data array', async () => {
		expect(await fetchRecipeLibrary()).toEqual([]);
	});
});
