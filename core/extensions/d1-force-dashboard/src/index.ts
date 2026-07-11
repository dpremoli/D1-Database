import { defineModule } from '@directus/extensions-sdk';
import ForceDashboard from './ForceDashboard.vue';

// Standalone, home-styled force-analysis explorer: sample -> operation -> detail
// -> graphs (6 force/FFT charts + the per-axis FRM fingerprint). Reads the
// machining_force_analysis rows populated by scripts/force_orchestrator.py.
export default defineModule({
	id: 'd1-force-dashboard',
	name: 'Force Analysis',
	icon: 'insights',
	routes: [{ path: '', component: ForceDashboard }],
});
