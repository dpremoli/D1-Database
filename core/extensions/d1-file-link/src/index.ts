import { defineInterface } from '@directus/extensions-sdk';
import FileLink from './FileLink.vue';

export default defineInterface({
	id: 'd1-file-link',
	name: 'File Path (copy / open)',
	icon: 'folder_open',
	description: 'Network file path with a one-click Copy button (paste into Explorer) and a best-effort Open link.',
	component: FileLink,
	types: ['string'],
	group: 'standard',
	options: [],
});
