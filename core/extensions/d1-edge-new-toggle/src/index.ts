import { defineInterface } from '@directus/extensions-sdk';
import EdgeNewToggle from './EdgeNewToggle.vue';

export default defineInterface({
	id: 'd1-edge-new-toggle',
	name: 'New Edge (inherit from insert edge)',
	icon: 'check_box',
	description:
		'Boolean toggle that auto-sets from the selected cutting insert edge (a fresh, unused edge ⇒ a new edge is in use). Stays manually overridable.',
	component: EdgeNewToggle,
	types: ['boolean'],
	group: 'standard',
	options: [],
});
