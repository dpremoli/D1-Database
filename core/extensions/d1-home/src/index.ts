import { defineModule } from '@directus/extensions-sdk';
import HomeView from './home.vue';
import RegisterSample from './register-sample.vue';
import PeopleView from './people.vue';
import PlaceholderPage from './pages/PlaceholderPage.vue';
import SamplePage from './pages/SamplePage.vue';

// A friendly landing page for lab users plus guided task screens, so day-to-day
// work starts somewhere warm and simple instead of a raw collection form.
//
// It also hosts the Explorer pages (docs/superpowers/specs/2026-10-06-explorer-pages-design.md):
// one formatted page per main record type, reached through recordRoute() in @d1/ui. A page that
// is not built yet renders a placeholder with a Data Studio link, so no link ever 404s.
const placeholder = (collection: string, title: string) => ({
	component: PlaceholderPage,
	props: (route: { params: Record<string, unknown> }) => ({
		collection,
		title,
		id: route.params.id as string | undefined,
	}),
});

export default defineModule({
	id: 'home',
	name: 'Home',
	icon: 'cottage',
	routes: [
		{ path: '', component: HomeView },
		{ path: 'register-sample', component: RegisterSample },
		{ path: 'people', component: PeopleView },
		{ path: 'projects', ...placeholder('projects', 'Projects') },
		{ path: 'projects/:id', ...placeholder('projects', 'Project') },
		{ path: 'campaigns/:id', ...placeholder('campaigns', 'Campaign') },
		{ path: 'samples/:id', component: SamplePage, props: true },
		{ path: 'operations/:id', ...placeholder('manufacturing_operations', 'Operation') },
		{ path: 'tests/:id', ...placeholder('test_sessions', 'Test session') },
	],
});
