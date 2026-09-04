<script setup lang="ts">
// Installs the standalone app's ForceHost, then renders the shared dashboard. The standalone
// app is cross-origin to Directus and Bearer-authenticated, so raw fetches carry an
// Authorization header and must NOT send cookies; assets cannot use a plain <a href> because
// the token would not travel with it.
import { ForceDashboard, setForceHost } from '@d1/force-plotting';
import { api, authHeaders } from '../directusClient';
import { authStore } from '../authStore';
import { getConfig } from '../config';

setForceHost({
	api,
	currentUser: () => authStore.currentUser.value,
	// Getters, not captured values: Settings > General can retarget these at runtime.
	get filterUrl() { return getConfig().filterUrl; },
	get diagUrl() { return getConfig().diagUrl; },
	get octreeUrl() { return getConfig().octreeUrl; },
	authHeaders,
	refreshAuth: () => authStore.refresh(),
	fetchCredentials: 'omit',
	// The record editors live in the Directus admin UI, which is a different origin here.
	openRecord: (collection, id) => {
		window.open(`${getConfig().directusUrl}/admin/content/${collection}/${id}`, '_blank', 'noopener');
	},
	// Assets are cross-origin and Bearer-authed, so fetch through the authenticated client
	// and save the blob rather than relying on an anchor href.
	downloadAsset: async (fileId) => {
		try {
			const res = await api.get(`/assets/${fileId}`, { params: { download: '' }, responseType: 'blob' });
			const url = URL.createObjectURL(res.data as Blob);
			const a = document.createElement('a');
			a.href = url; a.download = String(fileId);
			document.body.appendChild(a); a.click(); a.remove();
			setTimeout(() => URL.revokeObjectURL(url), 10_000);
		} catch { /* best-effort */ }
	},
	dense: true,
});
</script>

<template><ForceDashboard /></template>
