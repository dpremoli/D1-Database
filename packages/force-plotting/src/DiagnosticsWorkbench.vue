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
import LayerPanel from './LayerPanel.vue';
import WorkbenchPanel from './WorkbenchPanel.vue';
import SelectionInspector from './SelectionInspector.vue';
import BandwidthStrip from './BandwidthStrip.vue';
import { fetchD1an } from './diagAttrs';
import { fetchDiagPreview } from './diagPreview';
import { bucketEnvelope } from './liveCache';
import { clusterStats, computeStats, workingSetFromD1an } from './selection';
import type { ChannelKey, Selection, WorkingSet } from './selection';
import { DEFAULT_RECIPE, recipeChannels, recipesEquivalent, type Recipe } from './recipeChannels';
import {
	fetchLayers, saveLayer, deleteLayer, layersForRequest, type DiagLayer, type LayerRole,
} from './diagLayers';
import { fetchRecipeLibrary, type SavedRecipe } from './diagRecipes';
import { clusterColorCss } from './clusterPalette';
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

// --- paint layers ---------------------------------------------------------------------------
const layers = ref<DiagLayer[]>([]);
const activeLayerName = ref<string | null>(null);
const drawing = ref(false);
async function loadLayers() {
	try { layers.value = await fetchLayers(props.analysisId); }
	catch { layers.value = []; }
}
onMounted(loadLayers);
watch(() => props.analysisId, () => { activeLayerName.value = null; drawing.value = false; loadLayers(); });

const seedLayerNames = computed(() => layers.value.filter((l) => l.role === 'seed').map((l) => l.name));

// --- recipe library --------------------------------------------------------------------------
const library = ref<SavedRecipe[]>([]);
async function loadLibrary() {
	try { library.value = await fetchRecipeLibrary(); }
	catch { library.value = []; }
}
onMounted(loadLibrary);
function onApplyRecipe(r: Recipe) { recipe.value = r; }   // fires the debounced preview watch

// segment_id class index -> the seed layer that defines it (for the Spatial legend)
const segmentLegend = computed(() => {
	const seg = recipe.value.steps.find((s) => s.op === 'grow_segmentation' && s.on);
	const names = (seg?.inputs?.seeds as { layers?: string[] } | undefined)?.layers ?? [];
	return names.map((name, id) => ({ id, name }));
});

// Only masks with real geometry can bind to compute; an empty just-created layer is inert.
const boundMasks = computed(() =>
	layers.value.filter((l) => l.role === 'mask' && (l.geometry?.polygons?.length ?? 0) > 0));
const activeMask = computed(() =>
	boundMasks.value.find((l) => l.name === activeLayerName.value) ?? boundMasks.value[0] ?? null);

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
watch([recipe, () => layers.value, activeLayerName], () => {
	if (previewTimer) clearTimeout(previewTimer);
	previewTimer = setTimeout(runPreview, 400);
}, { deep: true });

// The recipe as sent to the preview service: a plain-JSON clone (never the reactive proxy —
// structuredClone throws on it) with the active mask bound onto radial_detrend. recipe.value
// itself is never mutated, so the bake payload and its hash are unaffected.
function recipeWithMask(): Recipe {
	if (!activeMask.value) return recipe.value;
	const r = JSON.parse(JSON.stringify(recipe.value)) as Recipe;
	for (const s of r.steps) {
		if (s.op === 'radial_detrend') {
			(s as { inputs?: unknown }).inputs = {
				mask: { layer: activeMask.value.name, required: false },
			};
		}
	}
	return r;
}

// Bake persists the recipe INCLUDING the mask binding (the geometry lives in diag_layer,
// which process_diag_row reads separately). Adopt that recipe as the local current one so
// the bake-stale comparator settles instead of reading "stale" forever.
function onBake() {
	const baked = recipeWithMask();
	recipe.value = JSON.parse(JSON.stringify(baked));
	emit('bake', baked);
}

async function runPreview() {
	previewAbort?.abort();
	// Show the bake when the recipe is unedited AND no mask is applied — either is a
	// non-baked state that needs a preview.
	if (!bakeStale.value && !activeMask.value) {
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
		const r = await fetchDiagPreview(
			props.analysisId, recipeWithMask(), null, ac.signal,
			activeMask.value ? layersForRequest([activeMask.value]) : undefined,
		);
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
	if (!ws) return null;
	// A paint mask leaves NaN in residZ for the excluded region; drop those points so the
	// envelope buckets (and the SVG path they feed) stay finite.
	let t = ws.t;
	let z = ws.residZ;
	if (!z.every((v) => Number.isFinite(v))) {
		const ti: number[] = [];
		const zi: number[] = [];
		for (let i = 0; i < ws.n; i++) {
			if (Number.isFinite(z[i])) { ti.push(t[i]); zi.push(z[i]); }
		}
		t = Float32Array.from(ti);
		z = Float32Array.from(zi);
	}
	return bucketEnvelope(t, z);
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

function _upsert(saved: DiagLayer) {
	const i = layers.value.findIndex((l) => l.layer_id === saved.layer_id);
	layers.value = i >= 0
		? layers.value.map((l) => (l.layer_id === saved.layer_id ? saved : l))
		: [...layers.value, saved];
}
async function onAddLayer(role: LayerRole): Promise<DiagLayer> {
	const existing = layers.value.filter((l) => l.role === role).length;
	const saved = await saveLayer({
		analysis_id: props.analysisId,
		name: `${role}-${existing + 1}`,
		role,
		geometry: { polygons: [] },
	});
	_upsert(saved);
	activeLayerName.value = saved.name;
	drawing.value = true;
	return saved;
}
async function onPolygon(ring: [number, number][]) {
	let target = layers.value.find((l) => l.name === activeLayerName.value);
	if (!target) target = await onAddLayer('mask');
	const geometry = { polygons: [...(target.geometry?.polygons ?? []), ring] };
	_upsert(await saveLayer({ ...target, geometry }));
}
async function onRenameLayer({ layer, name }: { layer: DiagLayer; name: string }) {
	const wasActive = activeLayerName.value === layer.name;
	const saved = await saveLayer({ ...layer, name });
	_upsert(saved);
	if (wasActive) activeLayerName.value = saved.name;
}
async function onDeleteLayer(layer: DiagLayer) {
	await deleteLayer(layer.layer_id);
	layers.value = layers.value.filter((l) => l.layer_id !== layer.layer_id);
	if (activeLayerName.value === layer.name) activeLayerName.value = null;
}

const stats = computed(() => (activeWS.value ? computeStats(activeWS.value, selection.value) : null));
const clusters = computed(() => (activeWS.value ? clusterStats(activeWS.value) : []));

const layout = ref([
	{ x: 0, y: 0, w: 3, h: 8, i: 'recipe' },
	{ x: 3, y: 0, w: 6, h: 8, i: 'spatial' },
	{ x: 9, y: 0, w: 3, h: 8, i: 'signal' },
]);

const multiMaskNote = computed(() =>
	boundMasks.value.length > 1 ? ' · only the selected mask is applied' : '');
const stateLabel = computed(() => {
	if (previewing.value) return `previewing recipe · approximate — Bake for exact numbers${multiMaskNote.value}`;
	if (previewWS.value) return `previewing recipe · ${previewMs.value ?? '?'} ms · approximate${multiMaskNote.value}`;
	if (bakeStale.value) return 'showing last bake · recipe edited since — Bake to apply';
	if (activeMask.value) return `mask applied in preview · Bake to persist${multiMaskNote.value}`;
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
						:seed-layer-names="seedLayerNames"
						:library="library"
						@bake="onBake"
						@apply="onApplyRecipe"
						@library-changed="loadLibrary"
					/>
				</WorkbenchPanel>

				<WorkbenchPanel v-else-if="item.i === 'spatial'" title="Spatial" icon="scatter_plot">
					<DiagScatter
						:working-set="activeWS"
						:channel="channel"
						:cluster-mode="clusterMode"
						:selection="selection"
						:point-size="2.6"
						:layers="layers"
						:active-layer-name="activeLayerName"
						:paint-mode="drawing ? 'draw' : 'off'"
						@polygon="onPolygon"
					/>
					<template #footer>
						<div class="dw-spatial-footer">
							<LayerPanel
								:layers="layers"
								v-model:active-name="activeLayerName"
								v-model:drawing="drawing"
								@add="onAddLayer"
								@rename="onRenameLayer"
								@delete="onDeleteLayer"
							/>
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
							<div v-if="channel === 'segmentId' && segmentLegend.length" class="dw-seg-legend">
								<span v-for="c in segmentLegend" :key="c.id" class="dw-seg-row">
									<span class="dw-seg-swatch" :style="{ background: clusterColorCss(c.id) }" />
									{{ c.id }} · {{ c.name }}
								</span>
							</div>
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
.dw-seg-legend { display: flex; flex-wrap: wrap; gap: 6px; font-size: 10px; color: var(--text-dim, #94a3b8); }
.dw-seg-row { display: inline-flex; align-items: center; gap: 4px; }
.dw-seg-swatch { width: 9px; height: 9px; border-radius: 2px; display: inline-block; }
.dw-channel-select { width: 100%; font-size: 12px; padding: 4px 6px; background: var(--bg-2, #111a33); color: var(--text, #e5e7eb); border: 1px solid var(--border, rgba(255,255,255,0.14)); border-radius: 6px; }
.dw-state { padding: 4px 12px; font-size: 11px; color: var(--text-dim, #94a3b8); border-top: 1px solid var(--border, rgba(255,255,255,0.1)); }
.dw-state.preview { color: #fcd34d; background: color-mix(in srgb, #d97706 12%, transparent); }
.dw-state.stale { color: #fca5a5; }
</style>
