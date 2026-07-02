import { defineInterface } from '@directus/extensions-sdk';
import ProjectInherit from './ProjectInherit.vue';

export default defineInterface({
	id: 'd1-project-inherit',
	name: 'Project (inherit from campaign)',
	icon: 'folder_special',
	description: 'M2O dropdown for project_id that auto-fills from the selected campaign when blank.',
	component: ProjectInherit,
	types: ['uuid'],
	group: 'standard',
	relational: true,
	options: [],
});
