import { defineModule } from '@directus/extensions-sdk';
import Crawler from './Crawler.vue';

// Admin control panel for the host-side force-crawler daemon (scripts/
// force_orchestrator.py --daemon). Directus runs in a container and cannot
// reach the archive share or spawn MATLAB, so this module only reads/writes
// the force_crawler_state singleton + machining_force_analysis queue; a human
// starts the daemon once on the host and it does the actual work.
export default defineModule({
	id: 'd1-force-crawler',
	name: 'Force Crawler',
	icon: 'dns',
	routes: [{ path: '', component: Crawler }],
});
