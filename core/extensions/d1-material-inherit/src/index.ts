import { defineInterface } from '@directus/extensions-sdk';
import MaterialInherit from './MaterialInherit.vue';

export default defineInterface({
	id: 'd1-material-inherit',
	name: 'Material / Alloy (inherit from sample)',
	icon: 'science',
	description: 'M2O dropdown for material_id that auto-fills from the input sample when no value is set.',
	component: MaterialInherit,
	types: ['uuid'],
	group: 'standard',
	options: [],
	relational: true,
});
