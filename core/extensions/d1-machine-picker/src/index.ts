import { defineInterface } from '@directus/extensions-sdk';
import MachinePicker from './MachinePicker.vue';

export default defineInterface({
	id: 'd1-machine-picker',
	name: 'Machine Picker (filtered by capability)',
	icon: 'precision_manufacturing',
	description: 'M2O machine picker filtered to equipment whose capabilities include the sibling process/test category. Works in create mode (unlike $CURRENT_ITEM filters).',
	component: MachinePicker,
	types: ['uuid', 'string'],
	localTypes: ['standard'],
	group: 'relational',
	relational: true,
	options: [
		{
			field: 'categoryField',
			name: 'Category field',
			type: 'string',
			meta: {
				interface: 'input',
				note: 'Sibling field whose value filters equipment.capabilities (e.g. process_category or test_category).',
			},
			schema: { default_value: 'process_category' },
		},
	],
});
