import { defineInterface } from '@directus/extensions-sdk';
import SampleCode from './SampleCode.vue';

export default defineInterface({
	id: 'd1-sample-code',
	name: 'Sample Code (auto-built)',
	icon: 'tag',
	description: 'Builds the sample code live from sequence-alloy-method-Y-M-D as the form is filled. Editable.',
	component: SampleCode,
	types: ['string'],
	group: 'standard',
	options: [],
});
