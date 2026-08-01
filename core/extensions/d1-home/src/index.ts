import { defineModule } from '@directus/extensions-sdk';
import HomeView from './home.vue';
import RegisterSample from './register-sample.vue';
import PeopleView from './people.vue';

// A friendly landing page for lab users plus guided task screens, so day-to-day
// work starts somewhere warm and simple instead of a raw collection form.
export default defineModule({
	id: 'home',
	name: 'Home',
	icon: 'cottage',
	routes: [
		{ path: '', component: HomeView },
		{ path: 'register-sample', component: RegisterSample },
		{ path: 'people', component: PeopleView },
	],
});
