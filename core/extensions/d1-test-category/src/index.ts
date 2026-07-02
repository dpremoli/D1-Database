import { defineInterface } from '@directus/extensions-sdk';
import TestCategory from './TestCategory.vue';

export default defineInterface({
	id: 'd1-test-category',
	name: 'Test Category (auto from test type)',
	icon: 'category',
	description: 'Infers the test category (NDE / destructive / dynamic) from the selected Test Type.',
	component: TestCategory,
	types: ['string'],
	group: 'standard',
	options: [],
});
