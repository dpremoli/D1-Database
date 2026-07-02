import { defineInterface } from '@directus/extensions-sdk';
import OperationCode from './OperationCode.vue';

export default defineInterface({
	id: 'd1-operation-code',
	name: 'Operation Code (auto-generated)',
	icon: 'tag',
	description:
		'Live-composes the machining operation code from the input sample, operation subtype, pass number and cutting parameters. Auto-fills but stays editable.',
	component: OperationCode,
	types: ['string'],
	group: 'standard',
	options: [],
});
