import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';
import { authStore } from './authStore';

const routes: RouteRecordRaw[] = [
	{ path: '/login', name: 'login', component: () => import('./LoginPage.vue'), meta: { public: true } },
	{ path: '/select', name: 'select', component: () => import('./SelectPage.vue') },
	// The extracted plotting explorer. Ported verbatim from the Directus module; it reads
	// ?operation= for deep-linking and otherwise manages its own in-view navigation.
	{ path: '/plot', name: 'plot', component: () => import('./force/ForceDashboard.vue') },
	// Recording/acquisition (Phase 2). Streams live frames from the local recorder backend.
	{ path: '/record', name: 'record', component: () => import('./record/RecordPage.vue') },
	{ path: '/', redirect: '/select' },
	{ path: '/:pathMatch(.*)*', redirect: '/select' },
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
