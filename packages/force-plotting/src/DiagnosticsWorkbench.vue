<script setup lang="ts">
// The Diagnostics Workbench: an editable processing pipeline, one or more full-resolution
// spatial views, the signal brush, the cluster table and the selection inspector — each a
// panel you can add, close, resize, rearrange or pop out to its own window, exactly like the
// Record tab (apps/force-app/web/src/record/RecordPage.vue).
//
// The recipe is a client-side object. Editing it debounce-fires POST /diag/preview, whose
// D1AN bytes feed the Signal chart and the Inspector. Each spatial view additionally recomputes
// its spatial step on the framed region at full resolution (see SpatialPanel.vue). The bake is
// the existing diag_status='pending' PATCH flow, emitted upward.
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { GridLayout, GridItem } from 'grid-layout-plus';
import ForceChart from './ForceChart.vue';
import SpatialPanel from './SpatialPanel.vue';
import ClusterTable from './ClusterTable.vue';
import RecipePanel from './RecipePanel.vue';
import LayerPanel from './LayerPanel.vue';
import WorkbenchPanel from './WorkbenchPanel.vue';
import SelectionInspector from './SelectionInspector.vue';
import BandwidthStrip from './BandwidthStrip.vue';
import InfoTip from './InfoTip.vue';
import { fetchD1an } from './diagAttrs';
import { fetchDiagPreview } from './diagPreview';
import type { ViewportResult } from './diagViewport';
import { bucketEnvelope } from './liveCache';
import { clusterStats, computeStats, workingSetFromD1an } from './selection';
import type { ClusterRow, Selection, WorkingSet } from './selection';
import {
	DEFAULT_RECIPE, recipeChannels, recipeProblems, recipesEquivalent, type Recipe,
} from './recipeChannels';
import { PANEL_HELP } from './diagHelp';
import {
	DIAG_LAYOUT_LS_KEY, DIAG_PANEL_TYPES, loadDiagLayout, newPanelInst, saveDiagLayout,
	type DiagPanelInst,
} from './diagPanels';
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
	/** true while the host is running a bake for this cut (owned by the page). */
	baking?: boolean;
	/** progress/failure text for the running bake, shown in the state strip. */
	bakeMessage?: string | null;
}>(), { initialRecipe: null, bakedRecipe: null, baking: false, bakeMessage: null });

const emit = defineEmits<{
	(e: 'bake', recipe: Recipe): void;
	(e: 'popout', payload: { type: string; channel?: string }): void;
}>();

// JSON clone, NOT structuredClone: `initialRecipe` arrives from the page's reactive row list,
// so it is a Vue Proxy, and structuredClone throws DataCloneError on a Proxy. That killed
// setup() outright — every cut with a saved diag_recipe rendered an empty workbench.
const recipe = ref<Recipe>(JSON.parse(JSON.stringify(props.initialRecipe ?? DEFAULT_RECIPE)));
const bakedWS = ref<WorkingSet | null>(null);
const previewWS = ref<WorkingSet | null>(null);
const loadError = ref<string | null>(null);
const previewing = ref(false);
const previewMs = ref<number | null>(null);
const previewErr = ref<string | null>(null);
const selection = ref<Selection>(null);
const skippedOps = ref<string[]>([]);
const recipeCollapsed = ref(false);

// Steps whose inputs no earlier enabled step produces. The service refuses these with a 422
// carrying a Python error string; catching it here marks the step and skips the doomed request.
const problems = computed(() => recipeProblems(recipe.value));
const recipeValid = computed(() => problems.value.length === 0);

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

// --- recipe library ------------------------------------------------------------------------
const library = ref<SavedRecipe[]>([]);
async function loadLibrary() {
	try { library.value = await fetchRecipeLibrary(); }
	catch { library.value = []; }
}
onMounted(loadLibrary);
function onApplyRecipe(r: Recipe) { recipe.value = r; }

const segmentLegend = computed(() => {
	const seg = recipe.value.steps.find((s) => s.op === 'grow_segmentation' && s.on);
	const names = (seg?.inputs?.seeds as { layers?: string[] } | undefined)?.layers ?? [];
	return names.map((name, id) => ({ id, name }));
});

const boundMasks = computed(() =>
	layers.value.filter((l) => l.role === 'mask' && (l.geometry?.polygons?.length ?? 0) > 0));
const activeMask = computed(() =>
	boundMasks.value.find((l) => l.name === activeLayerName.value) ?? boundMasks.value[0] ?? null);

const activeWS = computed(() => previewWS.value ?? bakedWS.value);
const bakeStale = computed(() =>
	!recipesEquivalent(recipe.value, props.bakedRecipe ?? DEFAULT_RECIPE));
const channelOptions = computed(() => recipeChannels(recipe.value));

async function loadBaked() {
	loadError.value = null;
	bakedWS.value = null;
	try {
		const base = `${useForceHost().octreeUrl}/diag/${props.diagPath}/`;
		bakedWS.value = workingSetFromD1an(await fetchD1an(`${base}attrs.d1an`));
	} catch (e: any) {
		loadError.value = e?.message || 'failed to load analysis attributes';
	}
}
onMounted(loadBaked);
watch(() => props.diagPath, () => { previewWS.value = null; loadBaked(); });

// Debounced preview: any recipe edit fires POST /diag/preview after 400 ms of quiet.
let previewTimer: ReturnType<typeof setTimeout> | null = null;
let previewAbort: AbortController | null = null;
watch([recipe, () => layers.value, activeLayerName], () => {
	if (previewTimer) clearTimeout(previewTimer);
	previewTimer = setTimeout(runPreview, 400);
}, { deep: true });

function recipeWithMask(): Recipe {
	if (!activeMask.value) return recipe.value;
	const r = JSON.parse(JSON.stringify(recipe.value)) as Recipe;
	for (const s of r.steps) {
		if (s.op === 'radial_detrend') {
			(s as { inputs?: unknown }).inputs = { mask: { layer: activeMask.value.name, required: false } };
		}
	}
	return r;
}

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
	if (!recipeValid.value) {
		previewing.value = false; previewErr.value = null; previewMs.value = null;
		return;
	}
	if (!bakeStale.value && !activeMask.value && !recipeHasBoundSeeds.value) {
		previewWS.value = null; previewErr.value = null; previewMs.value = null;
		return;
	}
	const ac = new AbortController();
	previewAbort = ac;
	previewing.value = true;
	previewErr.value = null;
	try {
		const r = await fetchDiagPreview(
			props.analysisId, recipeWithMask(), null, ac.signal,
			layers.value.length ? layersForRequestSafe() : undefined,
		);
		if (ac.signal.aborted) return;
		previewWS.value = workingSetFromD1an(r.attrs);
		previewMs.value = r.ms;
		skippedOps.value = r.skipped;
	} catch (e: any) {
		if (ac.signal.aborted || e?.name === 'AbortError') return;
		previewErr.value = e?.message || 'preview failed';
	} finally {
		if (previewAbort === ac) previewing.value = false;
	}
}
function layersForRequestSafe() { return layersForRequest(layers.value); }

// --- spatial panels: aggregate their independent viewport state ---------------------------
// Each SpatialPanel owns its own channel + recompute; the workbench only needs the union for
// the state strip ("something is recomputing") and one result for the cluster table.
const panelResults = reactive<Record<string, ViewportResult | null>>({});
const panelBusy = reactive<Record<string, boolean>>({});
const spatialRefs = new Map<string, { runViewport: (op: 'getis_ord' | 'hdbscan' | 'grow_segmentation', o?: { focus: boolean }) => void }>();
function bindSpatial(id: string, el: unknown) {
	if (el) spatialRefs.set(id, el as { runViewport: (op: 'getis_ord' | 'hdbscan' | 'grow_segmentation', o?: { focus: boolean }) => void });
	else { spatialRefs.delete(id); delete panelResults[id]; delete panelBusy[id]; }
}
const anyViewportBusy = computed(() => Object.values(panelBusy).some(Boolean));
// The cluster table describes whichever spatial view is currently showing an HDBSCAN result,
// so the table and that map cannot disagree. Falls back to the bake when none is.
const hdbscanResult = computed<ViewportResult | null>(() =>
	Object.values(panelResults).find((r) => r?.op === 'hdbscan') ?? null);

// "Run <op> on this view" from the Pipeline panel routes to the first spatial view.
function runStepOnView(op: 'getis_ord' | 'hdbscan' | 'grow_segmentation') {
	const first = layout.value.find((p) => p.type === 'spatial');
	if (first) spatialRefs.get(first.i)?.runViewport(op, { focus: true });
}

const chartData = computed(() => {
	const ws = activeWS.value;
	if (!ws) return null;
	let t = ws.t;
	let z = ws.residZ;
	if (!z.every((v) => Number.isFinite(v))) {
		const ti: number[] = []; const zi: number[] = [];
		for (let i = 0; i < ws.n; i++) if (Number.isFinite(z[i])) { ti.push(t[i]); zi.push(z[i]); }
		t = Float32Array.from(ti); z = Float32Array.from(zi);
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
	const name = `${role}-${Date.now().toString(36).slice(-4)}`;
	const saved = await saveLayer({ analysis_id: props.analysisId, name, role, geometry: { polygons: [] } });
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

function clustersFromViewport(r: ViewportResult): ClusterRow[] {
	const acc = new Map<number, { n: number; rMin: number; rMax: number }>();
	for (let i = 0; i < r.n; i++) {
		const id = r.value[i];
		if (!Number.isFinite(id)) continue;
		const key = id < 0 ? -1 : id;
		const rad = Math.hypot(r.x[i], r.y[i]);
		const a = acc.get(key);
		if (a) { a.n++; if (rad < a.rMin) a.rMin = rad; if (rad > a.rMax) a.rMax = rad; }
		else acc.set(key, { n: 1, rMin: rad, rMax: rad });
	}
	const total = r.n || 1;
	return [...acc.entries()]
		.map(([id, a]) => ({ id, n: a.n, fraction: a.n / total, meanAbsResidZ: null, maxGiStar: null, rMin: a.rMin, rMax: a.rMax }))
		.sort((a, b) => (a.id < 0 ? 1 : b.id < 0 ? -1 : b.n - a.n));
}
const clusters = computed<ClusterRow[]>(() => {
	const r = hdbscanResult.value;
	if (r) return clustersFromViewport(r);
	return activeWS.value ? clusterStats(activeWS.value) : [];
});
const clusterCaption = computed(() => {
	const r = hdbscanResult.value;
	if (r) return `${r.n.toLocaleString()} points in the framed view · full resolution`;
	const n = activeWS.value?.n ?? 0;
	return `${n.toLocaleString()} points · whole cut at analysis resolution`;
});
const clustersLive = computed(() => !!hdbscanResult.value
	|| layout.value.some((p) => p.type === 'spatial' && p.channel === 'clusterId')
	|| (activeWS.value ? clusterStats(activeWS.value).length > 0 : false));

// --- panel layout: add / close / reset / persist (RecordPage's model) ---------------------
const layout = ref<DiagPanelInst[]>(loadDiagLayout());
watch(layout, (l) => saveDiagLayout(l), { deep: true });
const addOpen = ref(false);
const addable = computed(() => Object.entries(DIAG_PANEL_TYPES).map(([type, m]) => ({
	type, ...m, disabled: !!m.single && layout.value.some((p) => p.type === type),
})));
function addPanel(type: string) {
	addOpen.value = false;
	const inst = newPanelInst(type, layout.value);
	if (inst) layout.value = [...layout.value, inst];
}
function closePanel(id: string) {
	layout.value = layout.value.filter((p) => p.i !== id);
}
function resetLayout() {
	try { localStorage.removeItem(DIAG_LAYOUT_LS_KEY); } catch { /* private mode */ }
	layout.value = loadDiagLayout();   // now returns the built-in default
}
function panelTitle(p: DiagPanelInst): string {
	if (p.type === 'spatial') {
		const opt = channelOptions.value.find((o) => o.key === p.channel);
		return opt ? `Spatial · ${opt.label.split(' — ')[0]}` : 'Spatial view';
	}
	return DIAG_PANEL_TYPES[p.type].title;
}
function setChannel(id: string, c: string) {
	const p = layout.value.find((x) => x.i === id);
	if (p) p.channel = c;
}
function onPopout(channel: string) {
	emit('popout', { type: 'spatial', channel });
}

// ---- Responsive grid height (ported from RecordPage) -------------------------------------
const GRID_MARGIN = 12;
const MIN_ROW_H = 18;
const BOTTOM_PAD = 2;
const gridEl = ref<HTMLElement | null>(null);
const availableHeight = ref(700);
function measureGrid() {
	if (!gridEl.value) return;
	const top = gridEl.value.getBoundingClientRect().top + window.scrollY;
	availableHeight.value = Math.max(320, Math.floor(window.innerHeight - top - BOTTOM_PAD));
}
const bottomRow = computed(() => layout.value.reduce((m, p) => Math.max(m, p.y + p.h), 0) || 1);
const rowHeight = computed(() =>
	Math.max(MIN_ROW_H, Math.floor((availableHeight.value - GRID_MARGIN) / bottomRow.value) - GRID_MARGIN));

const NARROW_BREAKPOINT = 640;
const narrow = ref(false);
function checkNarrow() { narrow.value = window.innerWidth < NARROW_BREAKPOINT; }
const stackedLayout = computed(() => {
	let y = 0;
	return layout.value.map((p) => { const out = { ...p, x: 0, w: 1, y }; y += p.h; return out; });
});
const displayLayout = computed({
	get: () => (narrow.value ? stackedLayout.value : layout.value),
	set: (v: DiagPanelInst[]) => {
		if (narrow.value) return;
		// grid-layout-plus rewrites x/y/w/h; keep our own `channel` field, which it drops.
		layout.value = v.map((p) => {
			const prev = layout.value.find((q) => q.i === p.i);
			return prev ? { ...p, channel: prev.channel } : p;
		});
	},
});

let gridRO: ResizeObserver | undefined;
onMounted(() => {
	gridRO = new ResizeObserver(measureGrid);
	if (gridEl.value) gridRO.observe(gridEl.value);
	measureGrid();
	checkNarrow();
	window.addEventListener('resize', measureGrid);
	window.addEventListener('resize', checkNarrow);
	document.addEventListener('click', () => { addOpen.value = false; });
});

const multiMaskNote = computed(() =>
	boundMasks.value.length > 1 ? ' · only the selected mask is applied' : '');

type StateKind = 'error' | 'busy' | 'preview' | 'stale' | 'baked';
const state = computed<{ kind: StateKind; text: string }>(() => {
	if (problems.value.length) {
		return { kind: 'error', text: `${problems.value.length} step${problems.value.length > 1 ? 's' : ''} cannot run — see the Pipeline panel` };
	}
	if (props.baking) {
		return { kind: 'busy', text: props.bakeMessage || 'Baking on the host — this rewrites the authoritative result…' };
	}
	if (props.bakeMessage) return { kind: 'error', text: props.bakeMessage };
	if (anyViewportBusy.value) return { kind: 'busy', text: 'Recomputing on the framed view at full resolution…' };
	if (previewing.value) return { kind: 'preview', text: `Updating the live preview — approximate; Bake for exact numbers${multiMaskNote.value}` };
	if (previewWS.value) return { kind: 'preview', text: `Live preview · ${previewMs.value ?? '?'} ms · approximate — Bake to make it authoritative${multiMaskNote.value}` };
	if (bakeStale.value) return { kind: 'stale', text: 'Showing the last bake — the recipe has been edited since. Bake to apply it.' };
	if (activeMask.value) return { kind: 'preview', text: `Mask applied in preview only — Bake to persist it${multiMaskNote.value}` };
	return { kind: 'baked', text: 'Showing the baked result for this cut — authoritative.' };
});

onBeforeUnmount(() => {
	previewAbort?.abort();
	if (previewTimer) clearTimeout(previewTimer);
	gridRO?.disconnect();
	window.removeEventListener('resize', measureGrid);
	window.removeEventListener('resize', checkNarrow);
});
</script>

<template>
	<div class="diag-workbench">
		<div v-if="loadError" class="dw-error">{{ loadError }}</div>
		<div ref="gridEl" class="dw-gridwrap">
			<div class="dw-panel-controls">
				<div class="dw-addwrap">
					<button class="dw-ctl" title="Add a panel" @click.stop="addOpen = !addOpen">
						<span class="material-symbols-rounded">add</span>
					</button>
					<div v-if="addOpen" class="dw-addmenu" @click.stop>
						<button v-for="a in addable" :key="a.type" :disabled="a.disabled" @click="addPanel(a.type)">
							<span class="material-symbols-rounded">{{ a.icon }}</span>{{ a.title }}
							<span v-if="a.disabled" class="dw-added">added</span>
						</button>
					</div>
				</div>
				<button class="dw-ctl" title="Reset panel layout" @click="resetLayout">
					<span class="material-symbols-rounded">grid_view</span>
				</button>
			</div>

			<GridLayout
				v-model:layout="displayLayout" :col-num="narrow ? 1 : 12" :row-height="rowHeight"
				:margin="[12, 12]" :is-draggable="!narrow" :is-resizable="!narrow"
				:use-css-transforms="true" :vertical-compact="true"
			>
				<GridItem
					v-for="item in displayLayout" :key="item.i"
					:x="item.x" :y="item.y" :w="item.w" :h="item.h" :i="item.i"
					drag-allow-from=".wb-panel-handle" :min-w="narrow ? 1 : 2" :min-h="3"
				>
					<WorkbenchPanel
						:title="panelTitle(item)" :icon="DIAG_PANEL_TYPES[item.type].icon"
						:closable="!(DIAG_PANEL_TYPES[item.type].single && ['recipe', 'signal'].includes(item.type))"
						@close="closePanel(item.i)"
					>
						<!-- Pipeline -->
						<RecipePanel
							v-if="item.type === 'recipe'"
							v-model:recipe="recipe"
							v-model:collapsed="recipeCollapsed"
							:baked="!!bakedWS" :bake-stale="bakeStale"
							:previewing="previewing" :preview-ms="previewMs" :preview-error="previewErr"
							:seed-layer-names="seedLayerNames" :library="library"
							:problems="problems" :baking="baking" :skipped-ops="skippedOps"
							:busy-op="anyViewportBusy ? 'any' : null"
							@bake="onBake" @apply="onApplyRecipe" @library-changed="loadLibrary"
							@run-step="runStepOnView"
						/>

						<!-- Spatial view (multi) -->
						<SpatialPanel
							v-else-if="item.type === 'spatial'"
							:ref="(el) => bindSpatial(item.i, el)"
							:analysis-id="analysisId"
							:octree-path="`${diagPath}/full`"
							:recipe="recipe" :recipe-valid="recipeValid"
							:channel-options="channelOptions"
							:layers="layers" :active-layer-name="activeLayerName"
							:selection="selection" :drawing="drawing"
							:initial-channel="item.channel"
							@polygon="onPolygon"
							@update:channel="(c) => setChannel(item.i, c)"
							@cluster-select="onClusterSelect"
							@result="(r) => panelResults[item.i] = r"
							@busy="(b) => panelBusy[item.i] = b"
							@popout="onPopout"
						/>

						<!-- Signal -->
						<template v-else-if="item.type === 'signal'">
							<div class="dw-signal-head">
								<span class="dw-signal-title">Anomaly z-score along the cut</span>
								<InfoTip :text="PANEL_HELP.signal" wide placement="left" />
							</div>
							<ForceChart
								v-if="chartData"
								title="resid_z (σ from normal for that radius) vs time"
								kind="env" :data="chartData" color="#f59e0b" x-unit="s" y-unit="σ"
								:crop-start="selection?.kind === 'time' ? selection.t0 : null"
								:crop-end="selection?.kind === 'time' ? selection.t1 : null"
								:crop-editable="true"
								@update:crop-start="onCropStart" @update:crop-end="onCropEnd"
							/>
							<div v-else class="dw-loading">loading…</div>
						</template>

						<!-- Clusters -->
						<template v-else-if="item.type === 'clusters'">
							<ClusterTable
								v-if="clustersLive"
								:rows="clusters" :caption="clusterCaption"
								:active-id="selection?.kind === 'cluster' ? selection.id : null"
								@select="onClusterSelect"
							/>
							<div v-else class="dw-loading">
								Colour a Spatial view by <code>cluster_id</code> to populate this.
							</div>
							<div v-if="segmentLegend.length" class="dw-seg-legend">
								<span v-for="c in segmentLegend" :key="c.id" class="dw-seg-row">
									<span class="dw-seg-swatch" :style="{ background: clusterColorCss(c.id) }" />
									{{ c.id }} · {{ c.name }}
								</span>
							</div>
						</template>

						<!-- Selection inspector -->
						<template v-else-if="item.type === 'inspector'">
							<SelectionInspector v-if="stats" :stats="stats" />
							<div v-else class="dw-loading">brush the Signal chart or pick a cluster</div>
						</template>

						<!-- Painted layers live in the Pipeline panel's footer -->
						<template v-if="item.type === 'recipe'" #footer>
							<div class="dw-layers-row">
								<LayerPanel
									:layers="layers"
									v-model:active-name="activeLayerName"
									v-model:drawing="drawing"
									@add="onAddLayer" @rename="onRenameLayer" @delete="onDeleteLayer"
								/>
								<InfoTip :text="PANEL_HELP.layers" placement="left" />
							</div>
						</template>
					</WorkbenchPanel>
				</GridItem>
			</GridLayout>
		</div>

		<div class="dw-state" :class="state.kind">
			<span class="dw-state-dot" />
			{{ state.text }}
		</div>
		<BandwidthStrip :metrics="props.diagMetrics as any" />
	</div>
</template>

<style scoped>
.diag-workbench { display: flex; flex-direction: column; min-height: 0; }
.dw-gridwrap { position: relative; margin: 8px 10px 0; }
.dw-gridwrap :deep(.vgl-layout) { margin: 0; }
.dw-gridwrap :deep(.vgl-item--placeholder) { background: rgba(56, 189, 248, 0.18); border-radius: 12px; }
.dw-gridwrap :deep(.vgl-item__resizer) { z-index: 5; }
.dw-error { padding: 8px 12px; color: var(--danger, #fca5a5); font-size: 12px; }
.dw-loading { display: flex; align-items: center; justify-content: center; height: 100%; padding: 12px; text-align: center; color: var(--text-dim); font-size: 12px; }
.dw-loading code { font-size: 11px; background: var(--bg-2, #111a33); padding: 1px 4px; border-radius: 4px; }

.dw-panel-controls { position: fixed; right: 20px; bottom: 56px; z-index: 25; display: flex; align-items: center; gap: 8px; }
.dw-addwrap { position: relative; }
.dw-ctl { display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 34px; border-radius: 9px; background: var(--bg-1, #0f172a); border: 1px solid var(--border, rgba(255,255,255,0.16)); color: var(--text-dim, #94a3b8); cursor: pointer; box-shadow: 0 4px 14px rgba(0,0,0,0.4); }
.dw-ctl:hover { color: var(--accent, #38bdf8); }
.dw-ctl .material-symbols-rounded { font-size: 19px; }
.dw-addmenu { position: absolute; right: 0; bottom: calc(100% + 8px); min-width: 210px; background: var(--bg-1, #0f172a); border: 1px solid var(--border, rgba(255,255,255,0.16)); border-radius: 10px; box-shadow: 0 10px 28px rgba(0,0,0,0.5); overflow: hidden; }
.dw-addmenu button { display: flex; align-items: center; gap: 8px; width: 100%; font: inherit; font-size: 12px; padding: 8px 11px; background: none; border: none; color: var(--text, #e5e7eb); cursor: pointer; text-align: left; }
.dw-addmenu button:hover:not(:disabled) { background: rgba(255,255,255,0.05); }
.dw-addmenu button:disabled { color: var(--text-dim, #94a3b8); cursor: default; }
.dw-addmenu .material-symbols-rounded { font-size: 16px; color: var(--text-dim, #94a3b8); }
.dw-added { margin-left: auto; font-size: 9.5px; text-transform: uppercase; letter-spacing: 0.03em; color: var(--text-dim, #94a3b8); }

.dw-seg-legend { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; padding: 0 8px 6px; font-size: 10px; color: var(--text-dim, #94a3b8); }
.dw-seg-row { display: inline-flex; align-items: center; gap: 4px; }
.dw-seg-swatch { width: 9px; height: 9px; border-radius: 2px; display: inline-block; }
.dw-layers-row { display: flex; align-items: flex-start; gap: 6px; }
.dw-layers-row > :first-child { flex: 1; min-width: 0; }

.dw-signal-head { display: flex; align-items: center; gap: 5px; padding: 2px 2px 4px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-dim, #94a3b8); }
.dw-signal-title { font-weight: 650; }

.dw-state { display: flex; align-items: center; gap: 7px; padding: 5px 12px; font-size: 11px; color: var(--text-dim, #94a3b8); border-top: 1px solid var(--border, rgba(255,255,255,0.1)); }
.dw-state-dot { flex: none; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.dw-state.preview { color: #fcd34d; background: color-mix(in srgb, #d97706 12%, transparent); }
.dw-state.busy { color: #7dd3fc; background: color-mix(in srgb, #38bdf8 12%, transparent); }
.dw-state.stale { color: #fca5a5; }
.dw-state.error { color: #fca5a5; background: color-mix(in srgb, #dc2626 14%, transparent); }
.dw-state.baked { color: #86efac; }
</style>
