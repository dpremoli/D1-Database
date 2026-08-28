import { createApp } from 'vue';
import { loadRuntimeConfig } from './config';
import { router } from './router';
import { setUnauthorizedHandler } from './directusClient';
import { installGlobalErrorReporting, reportClientError } from './clientLog';
import App from './App.vue';
import VIcon from './shims/VIcon.vue';
import VProgressCircular from './shims/VProgressCircular.vue';
import './theme'; // applies the persisted theme attribute before first paint
import './styles.css';

async function bootstrap() {
	// Honour an optional runtime /config.json before anything reads the service URLs.
	await loadRuntimeConfig();

	const app = createApp(App);

	// Register the two Directus global components the ported plotting UI relies on.
	app.component('v-icon', VIcon);
	app.component('v-progress-circular', VProgressCircular);

	app.use(router);

	// Vue-level errors (component render/setup/lifecycle) don't reach window.onerror, so they need
	// their own hook; window.onerror/unhandledrejection catch everything else (plain JS, promises).
	app.config.errorHandler = (err, _instance, info) => {
		console.error(err, info);
		reportClientError(`${(err as Error)?.stack || err} (${info})`, 'vue', router.currentRoute.value.fullPath);
	};
	installGlobalErrorReporting(() => router.currentRoute.value.fullPath);

	// When a token refresh fails mid-request, drop the user back to the login screen.
	setUnauthorizedHandler(() => {
		if (router.currentRoute.value.name !== 'login') {
			router.replace({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } });
		}
	});

	app.mount('#app');
}

bootstrap();
