import { defineInterface } from '@directus/extensions-sdk';
import GeometryPreviewComponent from './GeometryPreview.vue';

export default defineInterface({
	id: 'd1-geometry-preview',
	name: 'Sample Geometry Preview',
	icon: 'view_in_ar',
	description: 'Live SVG sketch of sample geometry based on form + dimension fields',
	component: GeometryPreviewComponent,
	types: ['alias'],
	localTypes: ['presentation'],
	group: 'presentation',
	options: [],
});
