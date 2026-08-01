import { defineInterface } from '@directus/extensions-sdk';
import ProcessCategory from './ProcessCategory.vue';

export default defineInterface({
	id: 'd1-process-category',
	name: 'Process Category (auto from method)',
	icon: 'category',
	description: 'Infers the process category from the selected Manufacturing Method and writes it so the matching parameter fields appear.',
	component: ProcessCategory,
	types: ['string'],
	group: 'standard',
	options: [],
});
