import { defineInterface } from '@directus/extensions-sdk';
import CompositionBarComponent from './CompositionBar.vue';

export default defineInterface({
	id: 'd1-composition-bar',
	name: 'Alloy Composition Bar',
	icon: 'stacked_bar_chart',
	description: 'Stacked horizontal wt% bar of the alloying-element breakdown',
	component: CompositionBarComponent,
	types: ['alias'],
	localTypes: ['presentation'],
	group: 'presentation',
	options: [],
});
