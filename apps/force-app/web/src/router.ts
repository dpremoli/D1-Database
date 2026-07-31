import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';
import { authStore } from './authStore';

const routes: RouteRecordRaw[] = [
	{ path: '/login', name: 'login', component: () => import('./LoginPage.vue'), meta: { public: true } },
	// Authenticated app: a persistent left-sidebar shell with the sections rendered inside it.
	{
		path: '/',
		component: () => import('./AppShell.vue'),
		children: [
			{ path: '', redirect: '/record' },
			{ path: 'record', name: 'record', component: () => import('./record/RecordPage.vue') },
			{ path: 'plot', name: 'plot', component: () => import('./force/ForceDashboard.vue') },
			{ path: 'labamp', name: 'labamp', component: () => import('./labamp/LabAmpPage.vue') },
			{ path: 'settings', name: 'settings', component: () => import('./settings/SettingsPage.vue') },
		],
	},
	{ path: '/:pathMatch(.*)*', redirect: '/record' },
];

export const router = createRouter({
	history: createWebHistory(),
	routes,
});

// Auth guard: anything not marked `public` requires a session (access or refresh token).
router.beforeEach((to) => {
	if (to.meta.public) return true;
	if (authStore.isAuthenticated.value) return true;
	return { name: 'login', query: to.fullPath !== '/' ? { redirect: to.fullPath } : undefined };
});
