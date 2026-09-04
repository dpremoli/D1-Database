<script setup lang="ts">
// The Diagnostics Workbench: tune-and-see. Three columns — the editable recipe, the spatial
// analysis cloud (channel-selectable, cluster overlay), and the signal brush — plus the
// selection inspector and a state strip that is honest about preview vs bake.
//
// The recipe is a client-side object. Editing a parameter debounce-fires POST /diag/preview,
// whose D1AN bytes replace the WorkingSet everything downstream reads. The bake stays the
// existing diag_status='pending' PATCH flow, emitted upward.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { GridLayout, GridItem } from 'grid-layout-plus';
import ForceChart from './ForceChart.vue';
import DiagOctreeView from './DiagOctreeView.vue';
import ClusterTable from './ClusterTable.vue';
import RecipePanel from './RecipePanel.vue';
import LayerPanel from './LayerPanel.vue';
import WorkbenchPanel from './WorkbenchPanel.vue';
import SelectionInspector from './SelectionInspector.vue';
import BandwidthStrip from './BandwidthStrip.vue';
import { fetchD1an } from './diagAttrs';
import { fetchDiagPreview } from './diagPreview';
import { fetchViewportCompute, type ViewportResult, type ViewportStep } from './diagViewport';
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

const recipeHasBoundSeeds = computed(() => recipe.value.steps.some((s) =>
	s.on && s.op === 'grow_segmentation'
	&& (((s.inputs?.seeds as { layers?: string[] } | undefined)?.layers?.length ?? 0) > 0)));

async function runPreview() {
	previewAbort?.abort();
	// Show the bake only when nothing overrides it: recipe unedited, no mask applied, no
	// seeds bound. Any of those is a non-baked state that needs a live preview.
	if (!bakeStale.value && !activeMask.value && !recipeHasBoundSeeds.value) {
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
		// Send every painted layer's geometry; the service rasterises only the ones a
		// binding names (radial_detrend's mask, grow_segmentation's seeds). The mask
		// binding is injected here; seed bindings are already in the recipe from RecipePanel.
		const r = await fetchDiagPreview(
			props.analysisId, recipeWithMask(), null, ac.signal,
			layers.value.length ? layersForRequest(layers.value) : undefined,
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

// --- Phase G: full-resolution viewport recompute -------------------------------------------
// The Spatial panel is the full-res octree (resid_z). Framing a region and settling fires a
// Gi* recompute on just those points; HDBSCAN / segmentation run on a button. The 256/rev
// bake stays authoritative -- this overlay is a preview at the resolution being looked at.
const analysisResult = ref<ViewportResult | null>(null);
const viewportBounds = ref<[number, number, number, number] | null>(null);
const viewportBusy = ref(false);
let viewportAbort: AbortController | null = null;
const recipeCollapsed = ref(false);

const OUTPUT_OF: Record<string, ChannelKey> = {
	getis_ord: 'giStar', hdbscan: 'clusterId', grow_segmentation: 'segmentId',
};
const OP_OF: Partial<Record<ChannelKey, 'getis_ord' | 'hdbscan' | 'grow_segmentation'>> = {
	giStar: 'getis_ord', clusterId: 'hdbscan', segmentId: 'grow_segmentation',
};
const analysisMode = computed<'continuous' | 'categorical'>(() =>
	channel.value === 'clusterId' || channel.value === 'segmentId' ? 'categorical' : 'continuous');

function stepParams(op: string): Record<string, unknown> {
	const s = recipe.value.steps.find((x) => x.op === op && x.on);
	return s ? { ...s.params } : {};
}
function stepInputs(op: string): Record<string, unknown> | undefined {
	const s = recipe.value.steps.find((x) => x.op === op && x.on);
	return s?.inputs as Record<string, unknown> | undefined;
}

async function runViewport(
	op: 'getis_ord' | 'hdbscan' | 'grow_segmentation',
	{ focus }: { focus: boolean } = { focus: true },
) {
	if (!viewportBounds.value) return;
	viewportAbort?.abort();
	const ac = new AbortController();
	viewportAbort = ac;
	viewportBusy.value = true;
	previewErr.value = null;
	try {
		const step: ViewportStep = { op, params: stepParams(op), inputs: stepInputs(op) };
		const r = await fetchViewportCompute(props.analysisId, viewportBounds.value, step, {
			layers: layers.value.length ? layersForRequest(layers.value) : undefined,
			signal: ac.signal,
			output: op === 'getis_ord' ? 'gi_star' : undefined,
		});
		if (ac.signal.aborted) return;
		analysisResult.value = r;
		if (focus) channel.value = OUTPUT_OF[op];
	} catch (e: any) {
		if (!ac.signal.aborted && e?.name !== 'AbortError') {
			previewErr.value = e?.message || 'viewport compute failed';
		}
	} finally {
		if (viewportAbort === ac) viewportBusy.value = false;
	}
}

function onBounds(b: [number, number, number, number]) {
	viewportBounds.value = b;
}

// The viewport overlay is per-cut: its x/y are the previous cut's spiral coords and its bbox
// is the previous cut's framing. Clear both on a cut switch so DiagOctreeView's load() ->
// rebuildAnalysis() does not draw the old Gi* points over the new octree.
watch(() => props.analysisId, () => {
	viewportAbort?.abort();
	analysisResult.value = null;
	viewportBounds.value = null;
});

// Manual run buttons for the enabled spatial steps (Gi* also auto-fires on settle).
const runButtons = computed(() => {
	const labels: Record<string, string> = {
		getis_ord: 'Run Gi*', hdbscan: 'Run HDBSCAN', grow_segmentation: 'Run segmentation',
	};
	return recipe.value.steps
		.filter((s) => s.on && s.op in labels)
		.map((s) => ({ op: s.op as 'getis_ord' | 'hdbscan' | 'grow_segmentation', label: labels[s.op] }));
});

// Auto Gi* on settle -- only while the analyst is actually viewing Gi*. Panning while
// studying a HDBSCAN result must not silently recompute or yank the channel back.
let giTimer: ReturnType<typeof setTimeout> | null = null;
function maybeAutoGi() {
	const gi = recipe.value.steps.find((s) => s.op === 'getis_ord' && s.on);
	if (!gi || channel.value !== 'giStar' || !viewportBounds.value) return;
	if (giTimer) clearTimeout(giTimer);
	giTimer = setTimeout(() => runViewport('getis_ord', { focus: false }), 600);
}
watch(viewportBounds, maybeAutoGi);
// Switching the channel to a spatial output recomputes when the shown overlay was NOT
// produced by that op -- otherwise switching giStar -> clusterId would render the stale Gi*
// z-scores through the categorical palette (int(mod(v,12))), which reads as fake clusters.
// The stale result is dropped immediately so nothing wrong is shown during the recompute.
watch(channel, (c) => {
	const op = OP_OF[c];
	if (!op || analysisResult.value?.op === op) return;
	if (!viewportBounds.value) return;   // nothing framed yet -- keep what's shown
	analysisResult.value = null;
	runViewport(op, { focus: false });
});
// The identity of just the step whose output is currently shown. A recipe edit re-runs the
// viewport ONLY when this changes -- editing radial_detrend / tsa / mount_deg while viewing a
// cluster_id overlay must not fire a full-resolution HDBSCAN that reflects nothing (the
// viewport reads pre-baked resid_z). Seed geometry lives in `layers`, not the recipe, so the
// segmentId case also watches the bound seed layers.
const activeSpatialStepKey = computed(() => {
	const op = OP_OF[channel.value];
	if (!op) return null;
	const s = recipe.value.steps.find((x) => x.op === op && x.on);
	if (!s) return null;
	const seedGeoms = op === 'grow_segmentation'
		? layers.value.filter((l) => l.role === 'seed').map((l) => [l.name, l.version, l.geometry])
		: null;
	return JSON.stringify({ params: s.params, inputs: s.inputs ?? null, seedGeoms });
});
let vpRecipeTimer: ReturnType<typeof setTimeout> | null = null;
watch(activeSpatialStepKey, () => {
	const op = OP_OF[channel.value];
	if (!op || analysisResult.value?.op !== op) return;
	if (vpRecipeTimer) clearTimeout(vpRecipeTimer);
	vpRecipeTimer = setTimeout(() => runViewport(op, { focus: false }), 500);
});

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
	// A time-based suffix, not `count + 1`: two fast clicks both read the same pre-save
	// count and collide on the (analysis_id, name) unique constraint. The analyst renames
	// from the LayerPanel anyway.
	const name = `${role}-${Date.now().toString(36).slice(-4)}`;
	const saved = await saveLayer({
		analysis_id: props.analysisId,
		name,
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

// Spatial is the hero: the full-res octree carries the interaction now. Recipe collapses to
// a rail; Signal sits under it.
const layout = ref([
	{ x: 0, y: 0, w: 9, h: 12, i: 'spatial' },
	{ x: 9, y: 0, w: 3, h: 7, i: 'recipe' },
	{ x: 9, y: 7, w: 3, h: 5, i: 'signal' },
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

onBeforeUnmount(() => {
	viewportAbort?.abort();
	previewAbort?.abort();
	if (giTimer) clearTimeout(giTimer);
	if (vpRecipeTimer) clearTimeout(vpRecipeTimer);
	if (previewTimer) clearTimeout(previewTimer);
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
						v-model:collapsed="recipeCollapsed"
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
						@run-step="(op) => runViewport(op, { focus: true })"
					/>
				</WorkbenchPanel>

				<WorkbenchPanel v-else-if="item.i === 'spatial'" title="Spatial" icon="scatter_plot">
					<DiagOctreeView
						:octree-path="`${diagPath}/full`"
						:channel="'residZ'"
						:colormap="'viridis'"
						:point-size="1.5"
						:selection="selection"
						:analysis-result="analysisResult"
						:analysis-mode="analysisMode"
						:layers="layers"
						:active-layer-name="activeLayerName"
						:paint-mode="drawing ? 'draw' : 'off'"
						@polygon="onPolygon"
						@bounds="onBounds"
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
							<div class="dw-vp-row">
								<button
									v-for="rb in runButtons" :key="rb.op"
									class="dw-vp-btn" :disabled="viewportBusy || !viewportBounds"
									@click="runViewport(rb.op, { focus: true })"
								>{{ rb.label }}</button>
								<span v-if="viewportBusy" class="dw-vp-busy">computing…</span>
								<span v-else-if="analysisResult" class="dw-vp-n">
									{{ analysisResult.n.toLocaleString() }} pts{{ analysisResult.ms != null ? ` · ${analysisResult.ms} ms` : '' }}
								</span>
							</div>
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
.dw-vp-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.dw-vp-btn { font: inherit; font-size: 11px; cursor: pointer; padding: 3px 8px; border-radius: 6px; color: var(--text, #e5e7eb); background: var(--bg-2, #111a33); border: 1px solid var(--border, rgba(255,255,255,0.18)); }
.dw-vp-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.dw-vp-busy { font-size: 10px; color: #fcd34d; }
.dw-vp-n { font-size: 10px; color: var(--text-dim, #94a3b8); font-variant-numeric: tabular-nums; }
.dw-state { padding: 4px 12px; font-size: 11px; color: var(--text-dim, #94a3b8); border-top: 1px solid var(--border, rgba(255,255,255,0.1)); }
.dw-state.preview { color: #fcd34d; background: color-mix(in srgb, #d97706 12%, transparent); }
.dw-state.stale { color: #fca5a5; }
</style>
