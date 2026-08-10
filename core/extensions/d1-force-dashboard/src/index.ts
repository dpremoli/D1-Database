import { defineModule } from '@directus/extensions-sdk';
import DirectusForceDashboard from './DirectusForceDashboard.vue';

// Standalone, home-styled force-analysis explorer: sample -> operation -> detail -> graphs
// (6 force/FFT charts + the per-axis FRM fingerprint). Reads the machining_force_analysis rows
// populated by scripts/force_orchestrator.py. The dashboard itself lives in
// packages/force-plotting and is shared with the standalone force app; this module only
// supplies the Directus-flavoured host (see DirectusForceDashboard.vue).
export default defineModule({
	id: 'd1-force-dashboard',
	name: 'Force Analysis',
	icon: 'insights',
	routes: [{ path: '', component: DirectusForceDashboard }],
});
