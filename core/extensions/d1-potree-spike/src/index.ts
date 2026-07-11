import { defineModule } from '@directus/extensions-sdk';
import Spike from './Spike.vue';

// THROWAWAY spike (2026-07-11): de-risk embedding a Potree/three.js LOD point-cloud
// viewer inside a Directus module extension before committing the full .mat→octree
// pipeline. Reachable by direct URL only (/admin/d1-potree-spike); NOT in the module
// bar. Delete once the integration questions (bundling / serving / attribute colouring)
// are answered.
export default defineModule({
	id: 'd1-potree-spike',
	name: 'Potree Spike',
	icon: 'scatter_plot',
	routes: [{ path: '', component: Spike }],
});
