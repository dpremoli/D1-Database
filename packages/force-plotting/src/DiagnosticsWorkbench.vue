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
import type { ChannelKey, ClusterRow, Selection, WorkingSet } from './selection';
import {
	DEFAULT_RECIPE, recipeChannels, recipeProblems, recipesEquivalent, type Recipe,
} from './recipeChannels';
import { CHANNEL_HELP, PANEL_HELP } from './diagHelp';
import InfoTip from './InfoTip.vue';
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

const emit = defineEmits<{ (e: 'bake', recipe: Recipe): void }>();

// JSON clone, NOT structuredClone: `initialRecipe` arrives from the page's reactive row list,
// so it is a Vue Proxy, and structuredClone throws DataCloneError on a Proxy. That killed
// setup() outright -- every cut with a saved diag_recipe rendered an empty workbench and a
// cascade of "Cannot read properties of undefined" from the template. A recipe is plain JSON
// by construction (it is posted as a request body), so the JSON round-trip is total here, and
// it is what the rest of this component already uses for the same reason.
const recipe = ref<Recipe>(JSON.parse(JSON.stringify(props.initialRecipe ?? DEFAULT_RECIPE)));
const bakedWS = ref<WorkingSet | null>(null);
const previewWS = ref<WorkingSet | null>(null);
const loadError = ref<string | null>(null);
const previewing = ref(false);
const previewMs = ref<number | null>(null);
const previewErr = ref<string | null>(null);
const selection = ref<Selection>(null);
const channel = ref<ChannelKey>('residZ');
// Ops the preview could not run (base-tier steps, which need full-rate input base.d1an does
// not carry). The service names them in X-Diag-Skipped instead of failing the whole request.
const skippedOps = ref<string[]>([]);

// Steps whose inputs no earlier enabled step produces. The service refuses these with a 422
// carrying a Python error string; catching it here lets the panel mark the step, name the fix,
// and skip the doomed request entirely.
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
	// An unsatisfiable recipe is refused by the service with a 422 whose body is a Python
	// error string. The panel already marks the offending step and names the fix, so don't
	// send the request and don't overwrite that with a raw server message.
	if (!recipeValid.value) {
		previewing.value = false;
		previewErr.value = null;
		previewMs.value = null;
		return;
	}
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
		skippedOps.value = r.skipped;
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
/** Which op the in-flight viewport compute is for, so its own button shows the progress. */
const viewportBusyOp = ref<string | null>(null);
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
	// Same guard as runPreview: an unsatisfiable recipe would 422 with a Python error string
	// over the top of the panel's own, better message.
	if (!viewportBounds.value || !recipeValid.value) return;
	viewportAbort?.abort();
	const ac = new AbortController();
	viewportAbort = ac;
	viewportBusy.value = true;
	viewportBusyOp.value = op;
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
		if (viewportAbort === ac) { viewportBusy.value = false; viewportBusyOp.value = null; }
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

// The cluster table must describe the SAME computation the Spatial view is showing. When a
// full-resolution viewport HDBSCAN is on screen, summarising the 256/rev bake instead put two
// different clusterings side by side with nothing saying so -- which reads as "my parameter
// change did nothing" when in fact the map updated and the table did not.
//
// The viewport response carries only {x, y, value}, so mean|z| and max gi* genuinely cannot be
// computed from it; those come back as null and the table renders them as "—" rather than
// borrowing the baked numbers for a different point set.
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
		.map(([id, a]) => ({
			id, n: a.n, fraction: a.n / total,
			meanAbsResidZ: null, maxGiStar: null, rMin: a.rMin, rMax: a.rMax,
		}))
		.sort((a, b) => (a.id < 0 ? 1 : b.id < 0 ? -1 : b.n - a.n));
}

const clusterSource = computed<'view' | 'bake'>(() =>
	analysisResult.value?.op === 'hdbscan' ? 'view' : 'bake');
const clusters = computed<ClusterRow[]>(() => {
	const r = analysisResult.value;
	if (r && r.op === 'hdbscan') return clustersFromViewport(r);
	return activeWS.value ? clusterStats(activeWS.value) : [];
});
const clusterCaption = computed(() => {
	const r = analysisResult.value;
	if (clusterSource.value === 'view' && r) {
		return `${r.n.toLocaleString()} points in the framed view · full resolution`;
	}
	const n = activeWS.value?.n ?? 0;
	return `${n.toLocaleString()} points · whole cut at analysis resolution`;
});

// Spatial is the hero: the full-res octree carries the interaction now. Recipe collapses to
// a rail; Signal sits under it. Both columns span the same rows so the layout has no ragged
// bottom edge.
const layout = ref([
	{ x: 0, y: 0, w: 9, h: 12, i: 'spatial' },
	{ x: 9, y: 0, w: 3, h: 7, i: 'recipe' },
	{ x: 9, y: 7, w: 3, h: 5, i: 'signal' },
]);

// ---- Responsive grid height ----------------------------------------------------------------
// Same approach as the Record tab (apps/force-app/web/src/record/RecordPage.vue), deliberately:
// grid-layout-plus sizes itself as `bottomRow * (rowHeight + marginY) + marginY`, so a FIXED
// row height pins the workspace to one pixel height regardless of window size — which is why
// this window opened with the panels crammed into the top and dead space beneath them.
// Measuring the space below the grid's own top and inverting that formula makes the panels
// fill the window exactly.
const GRID_MARGIN = 12;   // must match :margin="[12, 12]" on GridLayout below
const MIN_ROW_H = 18;     // floor: past this a tall layout scrolls rather than squashing to nothing
const BOTTOM_PAD = 2;

const gridEl = ref<HTMLElement | null>(null);
const availableHeight = ref(700);
function measureGrid() {
	if (!gridEl.value) return;
	// Document offset, not the viewport-relative rect: once the layout is taller than the
	// window it scrolls, and a scrolled rect has a negative top — using that inflates the
	// available height, which grows the rows, which makes the page taller still. The document
	// offset means the same thing wherever the page happens to be scrolled to.
	const top = gridEl.value.getBoundingClientRect().top + window.scrollY;
	availableHeight.value = Math.max(320, Math.floor(window.innerHeight - top - BOTTOM_PAD));
}
// From the LIVE layout, not the default: panels are drag-resizable, so the row span is
// arbitrary after any edit.
const bottomRow = computed(() => layout.value.reduce((m, p) => Math.max(m, p.y + p.h), 0) || 1);
const rowHeight = computed(() =>
	Math.max(MIN_ROW_H, Math.floor((availableHeight.value - GRID_MARGIN) / bottomRow.value) - GRID_MARGIN),
);

// Below this width the 12-column grid cannot lay panels side by side without squeezing their
// contents unreadable — fall back to a single-column stack, drag/resize off.
const NARROW_BREAKPOINT = 640;
const narrow = ref(false);
function checkNarrow() { narrow.value = window.innerWidth < NARROW_BREAKPOINT; }
const stackedLayout = computed(() => {
	let y = 0;
	return ['spatial', 'recipe', 'signal']
		.map((i) => layout.value.find((p) => p.i === i))
		.filter((p): p is NonNullable<typeof p> => !!p)
		.map((p) => { const out = { ...p, x: 0, w: 1, y }; y += p.h; return out; });
});
// Writable, exactly as RecordPage does it: v-model must be able to write a drag/resize back to
// the real layout, but the narrow stack is derived and must not be written through.
const displayLayout = computed({
	get: () => (narrow.value ? stackedLayout.value : layout.value),
	set: (v) => { if (!narrow.value) layout.value = v; },
});

let gridRO: ResizeObserver | undefined;
onMounted(() => {
	// ResizeObserver catches content reflow (the error banner appearing shifts the grid's top);
	// the window listener is the fallback, since RO fires unreliably under rapid or programmatic
	// viewport changes. Same pairing RecordPage and ForceDashboard use.
	gridRO = new ResizeObserver(measureGrid);
	if (gridEl.value) gridRO.observe(gridEl.value);
	measureGrid();
	checkNarrow();
	window.addEventListener('resize', measureGrid);
	window.addEventListener('resize', checkNarrow);
});

const multiMaskNote = computed(() =>
	boundMasks.value.length > 1 ? ' · only the selected mask is applied' : '');

// The state strip answers one question: what am I looking at, and is it authoritative?
// Ordered most-urgent first, and it must never claim "baked" while a bake is in flight.
type StateKind = 'error' | 'busy' | 'preview' | 'stale' | 'baked';
const state = computed<{ kind: StateKind; text: string }>(() => {
	if (problems.value.length) {
		return { kind: 'error', text: `${problems.value.length} step${problems.value.length > 1 ? 's' : ''} cannot run — see the Pipeline panel` };
	}
	if (props.baking) {
		return { kind: 'busy', text: props.bakeMessage || 'Baking on the host — this rewrites the authoritative result…' };
	}
	if (props.bakeMessage) return { kind: 'error', text: props.bakeMessage };
	if (viewportBusy.value) {
		return { kind: 'busy', text: 'Recomputing on the framed view at full resolution…' };
	}
	if (previewing.value) {
		return { kind: 'preview', text: `Updating the live preview — approximate; Bake for exact numbers${multiMaskNote.value}` };
	}
	if (previewWS.value) {
		return { kind: 'preview', text: `Live preview · ${previewMs.value ?? '?'} ms · approximate — Bake to make it authoritative${multiMaskNote.value}` };
	}
	if (bakeStale.value) {
		return { kind: 'stale', text: 'Showing the last bake — the recipe has been edited since. Bake to apply it.' };
	}
	if (activeMask.value) {
		return { kind: 'preview', text: `Mask applied in preview only — Bake to persist it${multiMaskNote.value}` };
	}
	return { kind: 'baked', text: 'Showing the baked result for this cut — authoritative.' };
});

const isolateClass = computed(() =>
	(selection.value?.kind === 'cluster' ? selection.value.id : null));

onBeforeUnmount(() => {
	viewportAbort?.abort();
	previewAbort?.abort();
	if (giTimer) clearTimeout(giTimer);
	if (vpRecipeTimer) clearTimeout(vpRecipeTimer);
	if (previewTimer) clearTimeout(previewTimer);
	gridRO?.disconnect();
	window.removeEventListener('resize', measureGrid);
	window.removeEventListener('resize', checkNarrow);
});
</script>

<template>
	<div class="diag-workbench">
		<div v-if="loadError" class="dw-error">{{ loadError }}</div>
		<!-- Wrapper exists purely so the responsive row-height maths has a real element to
		     measure from (a ref on <GridLayout> hands back the component instance, not a DOM
		     node) -- same as RecordPage's .gridwrap. -->
		<div ref="gridEl" class="dw-gridwrap">
		<GridLayout
			v-model:layout="displayLayout" :col-num="narrow ? 1 : 12" :row-height="rowHeight"
			:margin="[12, 12]" :is-draggable="!narrow" :is-resizable="!narrow"
			:use-css-transforms="true" :vertical-compact="true"
		>
			<GridItem v-for="item in displayLayout" :key="item.i" :x="item.x" :y="item.y" :w="item.w" :h="item.h" :i="item.i" drag-allow-from=".wb-panel-handle" :min-w="narrow ? 1 : 2" :min-h="3">
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
						:problems="problems"
						:busy-op="viewportBusy ? viewportBusyOp : null"
						:baking="baking"
						:skipped-ops="skippedOps"
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
						:isolate-class="isolateClass"
						:layers="layers"
						:active-layer-name="activeLayerName"
						:paint-mode="drawing ? 'draw' : 'off'"
						@polygon="onPolygon"
						@bounds="onBounds"
					/>
					<template #footer>
						<div class="dw-spatial-footer">
							<!-- One row: what the colour means, and where that colour came from. The
							     per-step "Run on this view" controls live in the Pipeline panel beside
							     the parameters they use, so there is exactly one place to run a step. -->
							<div class="dw-view-bar">
								<label class="dw-field">
									<span class="dw-field-label">
										Colour by
										<InfoTip :text="CHANNEL_HELP[channel] ?? 'Per-point analysis channel.'" placement="left" />
									</span>
									<select v-model="channel" class="dw-channel-select">
										<option v-for="o in channelOptions" :key="o.key" :value="o.key" :disabled="!o.produced">
											{{ o.label }}{{ o.produced ? '' : ' — step off' }}
										</option>
									</select>
								</label>
								<span class="dw-view-state">
									<template v-if="viewportBusy">computing on this view…</template>
									<template v-else-if="analysisResult">
										{{ analysisResult.n.toLocaleString() }} pts in view{{ analysisResult.ms != null ? ` · ${analysisResult.ms} ms` : '' }}
									</template>
									<template v-else-if="OP_OF[channel]">pan or zoom to compute on a region</template>
									<template v-else>baked map · whole cut</template>
								</span>
							</div>

							<div class="dw-layers-row">
								<LayerPanel
									:layers="layers"
									v-model:active-name="activeLayerName"
									v-model:drawing="drawing"
									@add="onAddLayer"
									@rename="onRenameLayer"
									@delete="onDeleteLayer"
								/>
								<InfoTip :text="PANEL_HELP.layers" placement="left" />
							</div>

							<ClusterTable
								v-if="clusterMode"
								:rows="clusters"
								:caption="clusterCaption"
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
					<div class="dw-signal-head">
						<span class="dw-signal-title">Anomaly z-score along the cut</span>
						<InfoTip :text="PANEL_HELP.signal" wide placement="left" />
					</div>
					<ForceChart
						v-if="chartData"
						title="resid_z (σ from normal for that radius) vs time"
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
		</div>

		<SelectionInspector v-if="stats" :stats="stats" />
		<div class="dw-state" :class="state.kind">
			<span class="dw-state-dot" />
			{{ state.text }}
		</div>
		<BandwidthStrip :metrics="props.diagMetrics as any" />
	</div>
</template>

<style scoped>
.diag-workbench { display: flex; flex-direction: column; min-height: 0; }
/* Wrapper the responsive row-height maths measures from. `flex: 1` would fight the computed
   row height (the grid sizes itself from rowHeight, not the other way round), so it is a plain
   block and the maths decides the height. */
.dw-gridwrap { margin: 8px 10px 0; }
.dw-gridwrap :deep(.vgl-layout) { margin: 0; }
.dw-gridwrap :deep(.vgl-item--placeholder) { background: rgba(56, 189, 248, 0.18); border-radius: 12px; }
.dw-gridwrap :deep(.vgl-item__resizer) { z-index: 5; }
.dw-error { padding: 8px 12px; color: var(--danger, #fca5a5); font-size: 12px; }
.dw-loading { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--text-dim); font-size: 12px; }
.dw-spatial-footer { display: flex; flex-direction: column; gap: 6px; max-height: 220px; overflow: auto; }
.dw-seg-legend { display: flex; flex-wrap: wrap; gap: 6px; font-size: 10px; color: var(--text-dim, #94a3b8); }
.dw-seg-row { display: inline-flex; align-items: center; gap: 4px; }
.dw-seg-swatch { width: 9px; height: 9px; border-radius: 2px; display: inline-block; }
.dw-channel-select { width: 100%; font-size: 12px; padding: 4px 6px; background: var(--bg-2, #111a33); color: var(--text, #e5e7eb); border: 1px solid var(--border, rgba(255,255,255,0.14)); border-radius: 6px; }

.dw-view-bar { display: flex; align-items: flex-end; gap: 10px; }
.dw-field { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.dw-field-label { display: inline-flex; align-items: center; gap: 4px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-dim, #94a3b8); }
.dw-view-state { flex: none; font-size: 10px; color: var(--text-dim, #94a3b8); font-variant-numeric: tabular-nums; padding-bottom: 5px; }
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
