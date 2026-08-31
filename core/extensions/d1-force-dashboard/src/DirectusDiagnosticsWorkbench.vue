<script setup lang="ts">
// Installs the Directus admin's ForceHost, then renders the shared DiagnosticsWorkbench.
// Mirrors DirectusForceDashboard.vue's pattern exactly. setForceHost is a module-level
// singleton (see host.ts); if both dashboards are ever mounted on the same page, the second
// call silently overwrites the first with an identical host shape -- safe, but worth knowing.
//
// operationId/diagPath/diagMetrics/totalPoints come from wherever the surrounding admin page
// determines the current operation -- passed in as props, not fetched here.
import { useApi, useStores } from '@directus/extensions-sdk';
import { useRouter } from 'vue-router';
import { DiagnosticsWorkbench, setForceHost } from '@d1/force-plotting';

const props = defineProps<{
	diagPath: string;
	diagMetrics: Record<string, unknown> | null;
	totalPoints: number;
}>();

const api = useApi();
const router = useRouter();
const { useUserStore } = useStores();
const userStore = useUserStore();

setForceHost({
	api,
	currentUser: () => userStore.currentUser,
	filterUrl: '/filter',
	octreeUrl: `${window.location.origin}/octrees`,
	authHeaders: () => ({}),
	fetchCredentials: 'include',
	openRecord: (collection, id) => { router.push(`/content/${collection}/${id}`); },
	downloadAsset: async (fileId) => {
		const a = document.createElement('a');
		a.href = `/assets/${fileId}?download`;
		a.rel = 'noopener';
		document.body.appendChild(a); a.click(); a.remove();
	},
	dense: false,
});
</script>

<template>
	<DiagnosticsWorkbench :diag-path="props.diagPath" :diag-metrics="props.diagMetrics" :total-points="props.totalPoints" />
</template>
