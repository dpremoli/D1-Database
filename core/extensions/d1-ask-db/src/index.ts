import { defineModule } from '@directus/extensions-sdk';
import ChatView from './chat.vue';

// "Ask the Database" — a full-page chat inside Directus that turns natural
// language into guarded, read-only SQL (via the d1-ask-endpoint proxy →
// llm-text-to-sql plugin) and renders the result as a table + optional chart.
export default defineModule({
	id: 'ask-db',
	name: 'Ask the Database',
	icon: 'chat',
	routes: [
		{
			path: '',
			component: ChatView,
		},
	],
});
