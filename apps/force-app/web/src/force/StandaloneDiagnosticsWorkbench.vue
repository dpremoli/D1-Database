<script setup lang="ts">
// Installs the standalone app's ForceHost, then renders the shared DiagnosticsWorkbench.
// Mirrors StandaloneForceDashboard.vue's pattern exactly.
import { DiagnosticsWorkbench, setForceHost } from '@d1/force-plotting';
import { api, authHeaders } from '../directusClient';
import { authStore } from '../authStore';
import { getConfig } from '../config';

const props = defineProps<{
	diagPath: string;
	diagMetrics: Record<string, unknown> | null;
	totalPoints: number;
}>();

setForceHost({
	api,
	currentUser: () => authStore.currentUser.value,
	// Getters, not captured values: Settings > General can retarget these at runtime.
	get filterUrl() { return getConfig().filterUrl; },
	get diagUrl() { return getConfig().diagUrl; },
	get octreeUrl() { return getConfig().octreeUrl; },
	authHeaders,
	fetchCredentials: 'omit',
	openRecord: (collection, id) => {
		window.open(`${getConfig().directusUrl}/admin/content/${collection}/${id}`, '_blank', 'noopener');
	},
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

<template>
	<DiagnosticsWorkbench :diag-path="props.diagPath" :diag-metrics="props.diagMetrics" :total-points="props.totalPoints" />
</template>
