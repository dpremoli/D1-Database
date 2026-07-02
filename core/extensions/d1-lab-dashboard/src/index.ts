import { defineModule } from '@directus/extensions-sdk';
import ModuleComponent from './Module.vue';
import MachiningDashboard from './views/MachiningDashboard.vue';
import SampleDashboard from './views/SampleDashboard.vue';
import NodeGraph from './views/NodeGraph.vue';

export default defineModule({
	id: 'd1-lab-dashboard',
	name: 'Lab Dashboard',
	icon: 'analytics',
	routes: [
		{
			path: '',
			component: ModuleComponent,
			children: [
				{ path: '', redirect: '/d1-lab-dashboard/machining' },
				{ path: 'machining', component: MachiningDashboard },
				{ path: 'samples', component: SampleDashboard },
				{ path: 'graph', component: NodeGraph },
			],
		},
	],
});
