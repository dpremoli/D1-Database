import { defineInterface } from '@directus/extensions-sdk';
import ArchiveLinks from './ArchiveLinks.vue';

// Presentation interface (alias field, no DB column). Shown on a record next to
// the native "Linked Data Files" M2M field: lists each linked archive file with
// a reliable Copy-UNC-path button and best-effort Open / Open-folder-in-Explorer
// links. No downloads — files are opened from the user's own mapped share.
export default defineInterface({
	id: 'd1-archive-links',
	name: 'Archive File Links (open in Explorer)',
	icon: 'folder_open',
	description:
		'Lists the linked archive files with a Copy UNC-path button and best-effort ' +
		'Open / Open-in-Explorer actions. Read-only; attach files via the M2M field.',
	component: ArchiveLinks,
	types: ['alias'],
	localTypes: ['presentation'],
	group: 'presentation',
	options: [
		{
			field: 'relationField',
			name: 'Linked-files field',
			type: 'string',
			meta: {
				interface: 'input',
				width: 'half',
				note: 'The M2M files field on this collection (e.g. data_files).',
			},
			schema: { default_value: 'data_files' },
		},
		{
			field: 'uncPrefix',
			name: 'UNC prefix',
			type: 'string',
			meta: {
				interface: 'input',
				width: 'full',
				note: 'Prepended to each file’s archive_path to form the network path.',
			},
			schema: { default_value: '\\\\uosfstore.shef.ac.uk\\shared\\star_group1\\' },
		},
	],
});
