<script setup lang="ts">
// A single Diagnostics Workbench panel in its own window — the second-monitor view. Mirrors
// the Record tab's /live/:panel pop-outs (LivePanelWindow.vue): install the app's ForceHost,
// read the target from the route, render one panel full-window.
//
// This is a VIEWER, not the editor: it colours by the LAST BAKED recipe's parameters. Editing
// the recipe stays in the main workbench window. A framed region still recomputes its spatial
// step at full resolution here, because that only needs the analysis id and the step params.
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import {
	SpatialPanel, DEFAULT_RECIPE, recipeChannels, setForceHost,
	fetchLayers, type DiagLayer, type Recipe,
} from '@d1/force-plotting';
import { api, authHeaders } from '../directusClient';
import { authStore } from '../authStore';
import { getConfig } from '../config';

setForceHost({
	api,
	currentUser: () => authStore.currentUser.value,
	get filterUrl() { return getConfig().filterUrl; },
	get diagUrl() { return getConfig().diagUrl; },
	get octreeUrl() { return getConfig().octreeUrl; },
	authHeaders,
	fetchCredentials: 'omit',
	openRecord: (collection, id) => {
		window.open(`${getConfig().directusUrl}/admin/content/${collection}/${id}`, '_blank', 'noopener');
	},
	downloadAsset: async () => { /* not used by a detached spatial view */ },
	dense: true,
});

const route = useRoute();
const analysisId = computed(() => String(route.params.analysisId || ''));
const channel = ref(String(route.query.channel || 'residZ'));

const diagPath = ref<string | null>(null);
const recipe = ref<Recipe>(DEFAULT_RECIPE);
const layers = ref<DiagLayer[]>([]);
const err = ref<string | null>(null);
const ready = computed(() => !!diagPath.value);

const channelOptions = computed(() => recipeChannels(recipe.value));

onMounted(async () => {
	try {
		const res = await api.get(`/items/machining_force_analysis/${analysisId.value}`, {
			params: { fields: ['diag_path', 'diag_status', 'diag_recipe'] },
		});
		const row = res.data?.data;
		if (row?.diag_status !== 'done' || !row?.diag_path) {
			err.value = 'This cut has no completed bake to view.';
			return;
		}
		diagPath.value = row.diag_path;
		if (row.diag_recipe) recipe.value = row.diag_recipe as Recipe;
		document.title = `Spatial · ${row.pass_code || analysisId.value.slice(0, 8)}`;
	} catch (e: any) {
		err.value = e?.message || 'failed to load the cut';
		return;
	}
	try { layers.value = await fetchLayers(analysisId.value); } catch { layers.value = []; }
});
</script>

<template>
	<div class="dpw">
		<header class="dpw-bar">
			<span class="dpw-kicker">Diagnostics · detached view</span>
			<span class="dpw-note">colours by the last baked recipe — edit in the main window</span>
		</header>
		<div class="dpw-body">
			<p v-if="err" class="dpw-err">{{ err }}</p>
			<SpatialPanel
				v-else-if="ready"
				:analysis-id="analysisId"
				:octree-path="`${diagPath}/full`"
				:recipe="recipe"
				:recipe-valid="true"
				:channel-options="channelOptions"
				:layers="layers"
				:active-layer-name="null"
				:selection="null"
				:drawing="false"
				:initial-channel="channel"
				no-popout
				@update:channel="(c) => channel = c"
			/>
			<p v-else class="dpw-loading">loading…</p>
		</div>
	</div>
</template>

<style scoped>
.dpw { display: flex; flex-direction: column; height: 100vh; background: var(--bg, #0b1020); }
.dpw-bar { display: flex; align-items: baseline; gap: 12px; padding: 8px 14px; border-bottom: 1px solid var(--border); }
.dpw-kicker { font-size: 12.5px; font-weight: 700; }
.dpw-note { font-size: 11px; color: var(--text-dim); }
.dpw-body { flex: 1; min-height: 0; padding: 10px 12px; }
.dpw-err, .dpw-loading { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--text-dim); font-size: 13px; }
.dpw-err { color: var(--danger, #fca5a5); }
</style>
