<script setup lang="ts">
// The Diagnostics Workbench: tune-and-see. Three columns — the editable recipe, the spatial
// analysis cloud (channel-selectable, cluster overlay), and the signal brush — plus the
// selection inspector and a state strip that is honest about preview vs bake.
//
// The recipe is a client-side object. Editing a parameter debounce-fires POST /diag/preview,
// whose D1AN bytes replace the WorkingSet everything downstream reads. The bake stays the
// existing diag_status='pending' PATCH flow, emitted upward.
import { computed, onMounted, ref, watch } from 'vue';
import { GridLayout, GridItem } from 'grid-layout-plus';
import ForceChart from './ForceChart.vue';
import DiagScatter from './DiagScatter.vue';
import ClusterTable from './ClusterTable.vue';
import RecipePanel from './RecipePanel.vue';
import WorkbenchPanel from './WorkbenchPanel.vue';
import SelectionInspector from './SelectionInspector.vue';
import BandwidthStrip from './BandwidthStrip.vue';
import { fetchD1an } from './diagAttrs';
import { fetchDiagPreview } from './diagPreview';
import { bucketEnvelope } from './liveCache';
import { clusterStats, computeStats, workingSetFromD1an } from './selection';
import type { ChannelKey, Selection, WorkingSet } from './selection';
import { DEFAULT_RECIPE, recipeChannels, recipesEquivalent, type Recipe } from './recipeChannels';
import { useForceHost } from './host';

const props = withDefaults(defineProps<{
	diagPath: string;
	analysisId: string;
	diagMetrics: Record<string, unknown> | null;
	totalPoints: number;
	initialRecipe?: Recipe | null;
	bakedRecipe?: Recipe | null;
}>(), { initialRecipe: null, bakedRecipe: null });

const emit = defineEmits<{ (e: 'bake', recipe: Recipe): void }>();

const recipe = ref<Recipe>(structuredClone(props.initialRecipe ?? DEFAULT_RECIPE));
const bakedWS = ref<WorkingSet | null>(null);
const previewWS = ref<WorkingSet | null>(null);
const loadError = ref<string | null>(null);
const previewing = ref(false);
const previewMs = ref<number | null>(null);
const previewErr = ref<string | null>(null);
const selection = ref<Selection>(null);
const channel = ref<ChannelKey>('residZ');

const activeWS = computed(() => previewWS.value ?? bakedWS.value);
const bakeStale = computed(() =>
	!recipesEquivalent(recipe.value, props.bakedRecipe ?? DEFAULT_RECIPE));
const channelOptions = computed(() => recipeChannels(recipe.value));
const clusterMode = computed(() => channel.value === 'clusterId');

async function loadBaked() {
	loadError.value = null;
	bakedWS.value = null;
	try {
		// diag_path is the bare operation id; the "diag/" segment is this component's to add —
		// /octrees/<id>/ is the raw spiral octree, a different artifact (200, not 404).
		const base = `${useForceHost().octreeUrl}/diag/${props.diagPath}/`;
		bakedWS.value = workingSetFromD1an(await fetchD1an(`${base}attrs.d1an`));
	} catch (e: any) {
		loadError.value = e?.message || 'failed to load analysis attributes';
	}
}
onMounted(loadBaked);
watch(() => props.diagPath, () => { previewWS.value = null; loadBaked(); });

// Debounced preview: any recipe edit fires POST /diag/preview after 400 ms of quiet, with the
// previous request aborted. The pattern filterChain.ts uses.
let previewTimer: ReturnType<typeof setTimeout> | null = null;
let previewAbort: AbortController | null = null;
watch(recipe, () => {
	if (previewTimer) clearTimeout(previewTimer);
	previewTimer = setTimeout(runPreview, 400);
}, { deep: true });

async function runPreview() {
	previewAbort?.abort();
	// An unedited recipe (equivalent to the bake) needs no preview — show the bake.
	if (!bakeStale.value) {
		previewWS.value = null;
		previewErr.value = null;
		previewMs.value = null;
		return;
	}
	const ac = new AbortController();
	previewAbort = ac;
	previewing.value = true;
	previewErr.value = null;
	try {
		const r = await fetchDiagPreview(props.analysisId, recipe.value, null, ac.signal);
		if (ac.signal.aborted) return;
		previewWS.value = workingSetFromD1an(r.attrs);
		previewMs.value = r.ms;
	} catch (e: any) {
		if (ac.signal.aborted || e?.name === 'AbortError') return;
		previewErr.value = e?.message || 'preview failed';
	} finally {
		if (previewAbort === ac) previewing.value = false;
	}
}

// If a produced-channel is deselected out from under the current view, fall back to resid_z.
watch(channelOptions, (opts) => {
	const cur = opts.find((o) => o.key === channel.value);
	if (cur && !cur.produced) channel.value = 'residZ';
});

const chartData = computed(() => {
	const ws = activeWS.value;
	return ws ? bucketEnvelope(ws.t, ws.residZ) : null;
});
function onCropStart(v: number) {
	const cur = selection.value;
	const t1 = cur && cur.kind === 'time' ? cur.t1 : (activeWS.value?.t.at(-1) ?? v);
	selection.value = { kind: 'time', t0: v, t1 };
}
function onCropEnd(v: number) {
	const cur = selection.value;
	const t0 = cur && cur.kind === 'time' ? cur.t0 : (activeWS.value?.t[0] ?? v);
	selection.value = { kind: 'time', t0, t1: v };
}
function onClusterSelect(id: number | null) {
	selection.value = id == null ? null : { kind: 'cluster', id };
}

const stats = computed(() => (activeWS.value ? computeStats(activeWS.value, selection.value) : null));
const clusters = computed(() => (activeWS.value ? clusterStats(activeWS.value) : []));

const layout = ref([
	{ x: 0, y: 0, w: 3, h: 8, i: 'recipe' },
	{ x: 3, y: 0, w: 6, h: 8, i: 'spatial' },
	{ x: 9, y: 0, w: 3, h: 8, i: 'signal' },
]);

const stateLabel = computed(() => {
	if (previewing.value) return 'previewing recipe · approximate — Bake for exact numbers';
	if (previewWS.value) return `previewing recipe · ${previewMs.value ?? '?'} ms · approximate`;
	if (bakeStale.value) return 'showing last bake · recipe edited since — Bake to apply';
	return 'baked';
});
</script>

<template>
	<div class="diag-workbench">
		<div v-if="loadError" class="dw-error">{{ loadError }}</div>
		<GridLayout v-model:layout="layout" :col-num="12" :row-height="40" :margin="[10, 10]" :is-resizable="true" :is-draggable="true">
			<GridItem v-for="item in layout" :key="item.i" :x="item.x" :y="item.y" :w="item.w" :h="item.h" :i="item.i" drag-allow-from=".wb-panel-handle">
				<WorkbenchPanel v-if="item.i === 'recipe'" title="Recipe" icon="tune">
					<RecipePanel
						v-model:recipe="recipe"
						:baked="!!bakedWS"
						:bake-stale="bakeStale"
						:previewing="previewing"
						:preview-ms="previewMs"
						:preview-error="previewErr"
						@bake="emit('bake', recipe)"
					/>
				</WorkbenchPanel>

				<WorkbenchPanel v-else-if="item.i === 'spatial'" title="Spatial" icon="scatter_plot">
					<DiagScatter
						:working-set="activeWS"
						:channel="channel"
						:cluster-mode="clusterMode"
						:selection="selection"
						:point-size="2.6"
					/>
					<template #footer>
						<div class="dw-spatial-footer">
							<select v-model="channel" class="dw-channel-select">
								<option v-for="o in channelOptions" :key="o.key" :value="o.key" :disabled="!o.produced">
									{{ o.label }}{{ o.produced ? '' : ' — step off' }}
								</option>
							</select>
							<ClusterTable
								v-if="clusterMode"
								:rows="clusters"
								:active-id="selection?.kind === 'cluster' ? selection.id : null"
								@select="onClusterSelect"
							/>
						</div>
					</template>
				</WorkbenchPanel>

				<WorkbenchPanel v-else-if="item.i === 'signal'" title="Signal" icon="show_chart">
					<ForceChart
						v-if="chartData"
						title="resid_z vs time"
						kind="env"
						:data="chartData"
						color="#f59e0b"
						x-unit="s"
						y-unit="σ"
						:crop-start="selection?.kind === 'time' ? selection.t0 : null"
						:crop-end="selection?.kind === 'time' ? selection.t1 : null"
						:crop-editable="true"
						@update:crop-start="onCropStart"
						@update:crop-end="onCropEnd"
					/>
					<div v-else class="dw-loading">loading…</div>
				</WorkbenchPanel>
			</GridItem>
		</GridLayout>

		<SelectionInspector v-if="stats" :stats="stats" />
		<div class="dw-state" :class="{ preview: previewing || previewWS, stale: bakeStale && !previewWS && !previewing }">
			{{ stateLabel }}
		</div>
		<BandwidthStrip :metrics="props.diagMetrics as any" />
	</div>
</template>

<style scoped>
.diag-workbench { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.diag-workbench :deep(.vgl-layout) { flex: 1; min-height: 0; }
.dw-error { padding: 8px 12px; color: var(--danger, #fca5a5); font-size: 12px; }
.dw-loading { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--text-dim); font-size: 12px; }
.dw-spatial-footer { display: flex; flex-direction: column; gap: 6px; max-height: 220px; overflow: auto; }
.dw-channel-select { width: 100%; font-size: 12px; padding: 4px 6px; background: var(--bg-2, #111a33); color: var(--text, #e5e7eb); border: 1px solid var(--border, rgba(255,255,255,0.14)); border-radius: 6px; }
.dw-state { padding: 4px 12px; font-size: 11px; color: var(--text-dim, #94a3b8); border-top: 1px solid var(--border, rgba(255,255,255,0.1)); }
.dw-state.preview { color: #fcd34d; background: color-mix(in srgb, #d97706 12%, transparent); }
.dw-state.stale { color: #fca5a5; }
</style>
