import { createApp } from 'vue';
import { loadRuntimeConfig } from './config';
import { router } from './router';
import { setUnauthorizedHandler } from './directusClient';
import App from './App.vue';
import VIcon from './shims/VIcon.vue';
import VProgressCircular from './shims/VProgressCircular.vue';
import './styles.css';

async function bootstrap() {
	// Honour an optional runtime /config.json before anything reads the service URLs.
	await loadRuntimeConfig();

	const app = createApp(App);

	// Register the two Directus global components the ported plotting UI relies on.
	app.component('v-icon', VIcon);
	app.component('v-progress-circular', VProgressCircular);

	app.use(router);

	// When a token refresh fails mid-request, drop the user back to the login screen.
	setUnauthorizedHandler(() => {
		if (router.currentRoute.value.name !== 'login') {
			router.replace({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } });
		}
	});

	app.mount('#app');
}

bootstrap();
