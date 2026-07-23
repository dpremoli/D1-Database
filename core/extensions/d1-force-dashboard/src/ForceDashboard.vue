<script setup lang="ts">
import { computed, nextTick, onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue';
import { useApi, useStores } from '@directus/extensions-sdk';
import { useRoute, useRouter } from 'vue-router';
import ForceChart from './ForceChart.vue';
import FrmCloud from './FrmCloud.vue';
import FrmOctree from './FrmOctree.vue';
import type { SpeedMode } from './liveCloud';
import { cacheGet, cachePut, decimateCache, parseCache, type Cache } from './liveCache';
import { computeSignalStats, type SignalStats } from './signalStats';
import { type FilterChain, chainActive, chainSummary, defaultChain, fetchFiltered, fetchFilteredFft } from './filterChain';

const api = useApi();
const router = useRouter();
const route = useRoute();
const { useUserStore } = useStores();
const userStore = useUserStore();

// Roles that see every sample/operation regardless of ownership (Administrator,
// Lab Admin). Everyone else (e.g. Lab Member) only sees analyses whose sample
// owner, operation owner, or operation operator resolves to their own
// people.person_id — this dashboard-level filter, not a Directus policy change,
// since it's the one place this scoping was asked for today.
const ADMIN_ROLE_IDS = new Set(['2ec9ca82-2dd5-42b5-b89f-1f4c6bf6ec4f', '10000001-0000-0000-0000-000000000001']);
const myPersonId = ref<string | null>(null);
// currentUser.role may be either the role object ({id}) or the bare id string,
// depending on how far the user store has hydrated — handle both, plus Directus's
// admin_access flag, so an actual admin is never wrongly ownership-filtered.
const isAdminRole = computed(() => {
	const cu = userStore.currentUser as any;
	const roleId = typeof cu?.role === 'string' ? cu.role : cu?.role?.id;
	return ADMIN_ROLE_IDS.has(roleId) || cu?.role?.admin_access === true || cu?.admin_access === true;
});

const AXES = ['Fx', 'Fy', 'Fz'] as const;
type Axis = typeof AXES[number];
const AXIS_COLOR: Record<Axis, string> = { Fx: '#dc2626', Fy: '#16a34a', Fz: '#2563eb' };  // red / green / blue

const loading = ref(true);
const rows = ref<any[]>([]);

const sampleSearch = ref('');
const opSearch = ref('');
// selectedSampleId: which sample is highlighted (set by clicking a sample OR an
// operation, so the samples list always shows where the current selection lives).
// filterSampleId: which sample the Operations list is scoped to — set ONLY by
// clicking a sample, so picking an operation never hides its siblings.
const selectedSampleId = ref<string | null>(null);
const filterSampleId = ref<string | null>(null);
const selectedRowId = ref<string | null>(null);
const detail = ref<any | null>(null);
const loadingDetail = ref(false);

const chartMode = ref<'force' | 'fft'>('force');
const hoverIndex = ref<number | null>(null);   // shared across the 3 charts
const axis = ref<Axis>('Fz');

// ---- Chart zoom -----------------------------------------------------------------
// The 3 axis charts share one x-window (they share an x-axis: time in force mode,
// frequency in FFT). zoomStart/zoomEnd are in x-units; null => full extent. A
// rect-zoom tool lets the user rubber-band a window; wheel zoom always works.
const zoomStart = ref<number | null>(null);
const zoomEnd = ref<number | null>(null);
const rectZoomTool = ref(false);
const zoomed = computed(() => zoomStart.value != null || zoomEnd.value != null);
function onChartZoom(v: { start: number; end: number } | null) {
	if (!v) { zoomStart.value = null; zoomEnd.value = null; return; }
	zoomStart.value = v.start; zoomEnd.value = v.end;
}
function resetZoom() { zoomStart.value = null; zoomEnd.value = null; }
// A new operation or a Force<->FFT switch changes the x-axis meaning entirely, so
// drop any stale zoom window.
watch([chartMode, selectedRowId], resetZoom);

// ---- Live mode ----------------------------------------------------------------
// Live augments the existing view in place (no separate panel): the FRM column
// becomes an interactive WebGL point cloud, the force plots gain draggable crop
// handles, and the operation's plot-driving metadata becomes editable. Everything
// recomputes client-side from the loaded live cache. A "Process" button (Tier 2)
// re-renders at a finer resolution on the host (archive is host-only).
// Default the point-cloud-vs-image choice by connection speed (a saved preference in
// the layout localStorage overrides this): fast link -> interactive cloud, slow/metered
// -> the lighter static image.
function fastConnection(): boolean {
	const c = (navigator as any).connection;
	if (!c) return true;                                   // unknown -> assume fast
	if (c.saveData) return false;                          // data-saver -> image
	if (typeof c.effectiveType === 'string') return c.effectiveType === '4g';
	if (typeof c.downlink === 'number') return c.downlink >= 5;   // Mbps
	return true;
}
const frmMode = ref<'figure' | 'lite' | 'full'>(fastConnection() ? 'lite' : 'figure');
// Editable geometry (seeded from the cache on load; user edits drive the cloud).
const cropStartSec = ref(0);
const cropEndSec = ref(0);
const editFeed = ref(0.1);
const editDiam = ref(80);
const editInnerDiam = ref(0);   // donut/diaphragm inner Ø (mm); 0 = solid disc
// Source snapshot of the op's cut params, so the editable boxes can highlight what the user
// changed vs what was loaded.
const srcCut = reactive({ feed: 0, diam: 0, inner: 0, ppr: 1, rate: 25600 });
const near = (a: number, b: number) => Math.abs(Number(a) - Number(b)) < 1e-6;
function seedCutFromDetail() {
	const d = detail.value; if (!d) return;
	srcCut.feed = Number(d.feed) || 0;
	srcCut.diam = Number(d.outer_diameter) || Number(d.cut_diameter) || 0;
	srcCut.inner = Number(d.inner_diameter) || 0;
	srcCut.ppr = Number(d.pulses_per_rev) || 1;
	srcCut.rate = Number(d.sample_rate) || 25600;
	if (srcCut.feed) editFeed.value = srcCut.feed;
	if (srcCut.diam) editDiam.value = srcCut.diam;
	editInnerDiam.value = srcCut.inner;
	editPpr.value = srcCut.ppr;
	editRate.value = srcCut.rate;
}
// The capture box edits the rate in kHz (Hz under the hood, driving the time-scale model).
const editRateKHz = computed({
	get: () => Math.round((editRate.value / 1000) * 100) / 100,
	set: (v: number) => { editRate.value = Math.max(1, Math.round(Number(v) * 1000)); },
});
watch(() => detail.value?.id, () => nextTick(seedCutFromDetail));
const speedMode = ref<SpeedMode>('measured');
const editRpm = ref(1000);
const editVc = ref(100);
const editRate = ref(25600);
const editPpr = ref(1);
let cacheFs = 25600;                              // the cache's own Fs, for the Rate time-scale
// Display options (client-side).
const plotStride = ref(1);
const gridding = ref(false);
const gridN = ref(400);
const pointSize = ref(1.4);
const colormap = ref('viridis');
// Tier-2 host render request.
const renderPoints = ref(5000000);   // full-res cut-window cache (host caps ~5M; >5M -> octree)
// Auto-route threshold = the crawler's live_cache_points setting (fetched on mount): a
// map with more points than the cache can hold is streamed as an octree instead. Falls
// back to 5M if the setting can't be read.
const octreeThreshold = ref(5_000_000);
const octreeMinNodePx = ref(1);
const octreeBudgetCap = ref(25_000_000);
const rendering = ref(false);
const renderMsg = ref<string | null>(null);
// ---- Full-resolution octree (Phase 2) ----------------------------------------------
// For ops too large for the client cache, the host builds a Potree octree from the raw
// .mat; the browser LOD-streams it (FrmOctree). octreeMode swaps the FRM column to it.
const gridFull = ref(false);   // "Gridded" sub-toggle, shown only in Full mode
const buildingOctree = ref(false);
const octreeMsg = ref<string | null>(null);
// Z-series: drive the octree's Z axis from a force series for a true 3D view.
const zSeries = ref<'none' | 'Fx' | 'Fy' | 'Fz'>('none');
const zScale = ref(0.35);
const octreeAvailable = computed(() => detail.value?.octree_status === 'done' && !!detail.value?.octree_path);
const octreeOn = computed(() => frmMode.value === 'full' && octreeAvailable.value);
async function buildOctree() {
	const d = detail.value;
	if (!d?.id || buildingOctree.value) return;
	buildingOctree.value = true; octreeMsg.value = 'Requesting full-res octree build on the host…';
	try {
		await api.patch(`/items/machining_force_analysis/${d.id}`, { octree_status: 'pending', octree_requested_at: new Date().toISOString() });
		octreeMsg.value = 'Building on the host (minutes for large ops)…';
		const deadline = Date.now() + 15 * 60 * 1000;
		while (Date.now() < deadline) {
			await new Promise((r) => setTimeout(r, 3000));
			const res = await api.get(`/items/machining_force_analysis/${d.id}`, { params: { fields: ['octree_status', 'octree_path', 'octree_points', 'octree_error'] } });
			const row = res.data?.data;
			if (row?.octree_status === 'done' && row.octree_path) {
				detail.value = { ...detail.value, octree_status: 'done', octree_path: row.octree_path, octree_points: row.octree_points };
				octreeMsg.value = null; frmMode.value = 'full'; return;
			}
			if (row?.octree_status === 'error') { octreeMsg.value = `Build failed: ${row.octree_error || 'unknown'}`; return; }
		}
		octreeMsg.value = 'Still building — check back shortly (is the force orchestrator running?).';
	} catch (e: any) {
		octreeMsg.value = e?.response?.status === 403 ? 'Not permitted (admin only) to request a host build.' : (e?.message || 'octree request failed');
	} finally { buildingOctree.value = false; }
}

// ---- Interpolated-grid octree (Gridded + Full-res) ---------------------------------
const gridAvailable = computed(() => detail.value?.grid_octree_status === 'done' && !!detail.value?.grid_octree_path);
// "Gridded" is a single mode-aware flag: in Live it drives client-side gridCloud binning
// (the old `gridding`); in Full-res it selects the interpolated-grid octree.
const gridActive = computed(() => frmMode.value === 'full' && gridFull.value && gridAvailable.value);
const gridFidelityPct = computed(() => {
	const f = detail.value?.grid_fidelity;
	return (f == null || Number.isNaN(Number(f))) ? null : Math.round(Number(f) * 100);
});
async function buildGridOctree() {
	const d = detail.value;
	if (!d?.id || buildingOctree.value) return;
	buildingOctree.value = true; octreeMsg.value = 'Requesting interpolated-grid build on the host…';
	try {
		await api.patch(`/items/machining_force_analysis/${d.id}`, { grid_octree_status: 'pending', grid_octree_requested_at: new Date().toISOString() });
		octreeMsg.value = 'Interpolating grid on the host (minutes for large ops)…';
		const deadline = Date.now() + 15 * 60 * 1000;
		while (Date.now() < deadline) {
			await new Promise((r) => setTimeout(r, 3000));
			const res = await api.get(`/items/machining_force_analysis/${d.id}`, { params: { fields: ['grid_octree_status', 'grid_octree_path', 'grid_octree_points', 'grid_octree_error', 'grid_fidelity', 'grid_arm_ratio', 'grid_cell_mm'] } });
			const row = res.data?.data;
			if (row?.grid_octree_status === 'done' && row.grid_octree_path) {
				detail.value = { ...detail.value, grid_octree_status: 'done', grid_octree_path: row.grid_octree_path,
					grid_octree_points: row.grid_octree_points, grid_fidelity: row.grid_fidelity,
					grid_arm_ratio: row.grid_arm_ratio, grid_cell_mm: row.grid_cell_mm };
				octreeMsg.value = null; return;
			}
			if (row?.grid_octree_status === 'error') { octreeMsg.value = `Grid build failed: ${row.grid_octree_error || 'unknown'}`; return; }
		}
		octreeMsg.value = 'Still building — check back shortly (is the force orchestrator running?).';
	} catch (e: any) {
		octreeMsg.value = e?.response?.status === 403 ? 'Not permitted (admin only) to request a host build.' : (e?.message || 'grid request failed');
	} finally { buildingOctree.value = false; }
}
// When the user turns on Gridded in Full-res and no grid octree exists yet, build it.
watch(() => [gridFull.value, frmMode.value], () => {
	if (gridFull.value && frmMode.value === 'full' && !gridAvailable.value && !buildingOctree.value) buildGridOctree();
});

// Displayed-vs-full resolution readout. "Full" = the map's native resolution (the octree
// total when built, else the cut-window sample count); "displayed" = what the active
// viewer renders right now (the Live rebuild count, or the octree's LOD-visible count).
const displayedPoints = ref(0);
const fullResPoints = computed<number | null>(() => {
	const d = detail.value; if (!d) return null;
	if (d.octree_points) return Number(d.octree_points);
	if (d.cut_start_idx != null && d.cut_end_idx != null) return Math.max(0, d.cut_end_idx - d.cut_start_idx);
	return null;
});
const resolutionPct = computed(() => {
	const f = fullResPoints.value;
	if (!f || !displayedPoints.value) return null;
	return Math.min(100, Math.round((displayedPoints.value / f) * 100));
});
function fmtPts(n: number | null): string {
	if (n == null) return '—';
	if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
	if (n >= 1e3) return `${(n / 1e3).toFixed(0)}k`;
	return String(n);
}
// Auto-route: when a map exceeds the octree threshold AND its octree is already built,
// default to the LOD octree view. We deliberately do NOT auto-trigger a host build here —
// that needs the daemon and takes minutes, and its progress message was leaking over the
// live cloud. Building is an explicit action (the Full-res button). Smaller maps, or large
// ones without an octree yet, stay on the Live/PNG path.
function pickDefaultMode(): 'figure' | 'lite' | 'full' {
	// Adjust the CURRENT mode for the new op rather than recomputing from scratch —
	// recomputing stomped an explicit user click that landed while the detail was still
	// loading (click "Figure" -> detail arrives -> watch flips back to Lite). Auto-route
	// UP to Full for big maps (documented behaviour); otherwise only downgrade when the
	// current mode isn't available for this op.
	const m = frmMode.value;
	const f = fullResPoints.value;
	if (octreeAvailable.value && f && f > octreeThreshold.value) return 'full';
	if (m === 'lite') return liveAvailable.value ? 'lite' : 'figure';
	if (m === 'full') return octreeAvailable.value ? 'full' : (liveAvailable.value && fastConnection() ? 'lite' : 'figure');
	return 'figure';
}
watch(() => detail.value?.id, () => {
	displayedPoints.value = 0;
	octreeMsg.value = null;   // clear any stale build message from the previous op
	// Reset the Live crop handles to the new op's auto-crop immediately (else the
	// previous op's crop lines linger until its live cache reloads). onCloudLoaded then
	// refines these from the cache once it arrives.
	if (cropWindow.value) { cropStartSec.value = cropWindow.value.start; cropEndSec.value = cropWindow.value.end; }
	else { cropStartSec.value = 0; cropEndSec.value = 0; }
	gridFull.value = false;
	frmMode.value = pickDefaultMode();
});
// Persist the inner diameter to the op (debounced) so a reprocess / octree build picks it up
// (the orchestrator threads inner_diameter into MATLAB). Live reflects it instantly client-side.
let innerPatchTimer = 0;
watch(editInnerDiam, (v) => {
	const d = detail.value; if (!d?.id) return;
	if (Number(v) === Number(d.inner_diameter || 0)) return;
	clearTimeout(innerPatchTimer);
	innerPatchTimer = window.setTimeout(async () => {
		try { await api.patch(`/items/machining_force_analysis/${d.id}`, { inner_diameter: Number(v) || 0 }); d.inner_diameter = Number(v) || 0; } catch { /* ignore */ }
	}, 600);
});

// Same for the outer diameter: persist edits as an override so host rebuilds use them
// (the .mat metadata CutDiameter is sometimes wrong). Editing back to the metadata value
// clears the override (NULL = follow metadata again). Seeding on load is guarded out.
let outerPatchTimer = 0;
watch(editDiam, (v) => {
	const d = detail.value; if (!d?.id) return;
	const nv = Number(v) || 0;
	const cur = Number(d.outer_diameter || 0);
	const meta = Number(d.cut_diameter || 0);
	if (nv === cur) return;                                       // unchanged vs stored override
	if (cur === 0 && (nv === 0 || Math.abs(nv - meta) < 1e-6)) return;   // just the metadata seed
	clearTimeout(outerPatchTimer);
	outerPatchTimer = window.setTimeout(async () => {
		const store = Math.abs(nv - meta) < 1e-6 ? null : nv;      // back-to-metadata clears it
		try { await api.patch(`/items/machining_force_analysis/${d.id}`, { outer_diameter: store }); d.outer_diameter = store; } catch { /* ignore */ }
	}, 600);
});

// ---- Signal statistics panel (collapsed by default) --------------------------------
// Post-mortem stats computed client-side from the live cache: mean/RMS/min/max between
// the crop lines per axis, plus whole-signal effective bit depth and rail/clip analysis
// (over-range detection). Reuses the FrmCloud LRU so Lite mode costs nothing extra; if
// the cache isn't downloaded yet the panel offers an explicit compute (= download).
// One accordion open at a time in the detail column: Operation detail | Signal statistics
// | Signal filters are mutually exclusive (opening one folds the others).
const openPanel = ref<'detail' | 'display' | 'stats' | 'filters' | null>('detail');
function togglePanel(p: 'detail' | 'display' | 'stats' | 'filters') { openPanel.value = openPanel.value === p ? null : p; }
const opDetailOpen = computed(() => openPanel.value === 'detail');
const displayPanelOpen = computed(() => openPanel.value === 'display');
const statsOpen = computed(() => openPanel.value === 'stats');
const STAT_AXES = ['Fx', 'Fy', 'Fz'] as const;
const sigStats = ref<SignalStats | null>(null);
const statsBusy = ref(false);
const statsErr = ref<string | null>(null);
const statsCacheMb = computed(() => {
	const d = detail.value; if (!d?.cut_start_idx || !d?.cut_end_idx) return null;
	const pts = Math.min(d.cut_end_idx - d.cut_start_idx, octreeThreshold.value);
	return Math.round((pts * 24) / 1e6);   // 6 float32 arrays per sample
});
async function computeStats() {
	const d = detail.value;
	if (!d?.live_cache_file || statsBusy.value) return;
	statsBusy.value = true; statsErr.value = null;
	try {
		let c = cacheGet(d.live_cache_file);
		if (!c) {
			const res = await api.get(`/assets/${d.live_cache_file}`, { responseType: 'arraybuffer' });
			c = parseCache(res.data as ArrayBuffer);
			cachePut(d.live_cache_file, c);
		}
		const cs = cropStartSec.value || c.csSec, ce = cropEndSec.value || c.ceSec;
		sigStats.value = computeSignalStats(c, cs, ce);
	} catch (e: any) {
		statsErr.value = e?.message || 'failed to compute statistics';
	} finally { statsBusy.value = false; }
}
// Recompute (cheap, cache already local) when the crop moves while the panel is open.
let statsTimer = 0;
watch(() => [cropStartSec.value, cropEndSec.value], () => {
	if (!statsOpen.value || !sigStats.value) return;
	clearTimeout(statsTimer);
	statsTimer = window.setTimeout(computeStats, 400);
});
watch(() => detail.value?.id, () => { sigStats.value = null; statsErr.value = null; });
watch(statsOpen, (open) => {
	// auto-compute on first open when the cache is already local (e.g. Lite was on)
	if (open && !sigStats.value && detail.value?.live_cache_file && cacheGet(detail.value.live_cache_file)) computeStats();
});
function fmtStat(v: number): string {
	const a = Math.abs(v);
	if (!Number.isFinite(v)) return '—';
	if (a >= 1000) return (v / 1000).toFixed(2) + 'k';
	if (a >= 10) return v.toFixed(1);
	return v.toFixed(2);
}

// ---- Signal-filter suite -----------------------------------------------------------
// Interactive: the working chain is previewed by the host filter-service on the live
// cache; raw + filtered render side-by-side in two linked viewports (compareView shared).
// Baking patches the op's filter_chain + reprocesses so ALL outputs are filtered.
const filtersOpen = computed(() => openPanel.value === 'filters');
const workChain = ref<FilterChain>(defaultChain());
const filteredCache = ref<Cache | null>(null);
// The RAW pane in compare mode plots the SAME decimated samples as the filtered pane
// (identical spiral positions; only colour differs) — the service's stride applied to the
// local full cache. Null until the first preview resolves, then the raw pane switches to it.
const rawDecimatedCache = ref<Cache | null>(null);
const filterBusy = ref(false);
const filterErr = ref<string | null>(null);
const filterSkipped = ref<string[]>([]);
const filterFftOverlay = ref<{ f: number[]; amp: number[] } | null>(null);
const baking = ref(false);
const profiles = ref<any[]>([]);
const compareOn = computed(() => liveOn.value && chainActive(workChain.value) && filtersOpen.value);
// Both live panes share ONE view object so pan/zoom in either drives both.
const compareView = reactive({ cx: 0, cy: 0, span: 1, active: false });
function mergeChain(raw: any): FilterChain {
	const d = defaultChain();
	if (!raw) return d;
	// deep-merge each stage over the defaults so chains saved before a stage existed
	// (e.g. pre-highpass) don't leave undefined stages that crash the template.
	return {
		despike: { ...d.despike, ...(raw.despike || {}) },
		detrend: { ...d.detrend, ...(raw.detrend || {}) },
		highpass: { ...d.highpass, ...(raw.highpass || {}) },
		lowpass: { ...d.lowpass, ...(raw.lowpass || {}) },
		notch: { ...d.notch, ...(raw.notch || {}) },
	};
}
// savedChain = the op's persisted filter_chain (from the DB), regardless of how it was applied.
// filterBaked = every derived output has been reprocessed with it (heavy bake); otherwise it's a
// LIGHT apply — the chain is the op's default but only Lite recomputes it live (Full/PNG stay raw).
const savedChain = computed<FilterChain | null>(() => {
	const fc = detail.value?.filter_chain;
	if (!fc) return null;
	return mergeChain(typeof fc === 'string' ? JSON.parse(fc) : fc);
});
const filterBaked = computed(() => detail.value?.filter_baked === true);
const bakedChain = computed<FilterChain | null>(() => (filterBaked.value ? savedChain.value : null));
const appliedLight = computed<boolean>(() => !!savedChain.value && !filterBaked.value);
// The single filtered pane: a light-applied op renders one Lite cloud recomputed from filteredCache
// (the compare panes only appear while the Filters panel is open for tuning). Baked ops need no solo
// pane — their loaded cache is already filtered, so the normal Lite pane shows the filtered signal.
const filteredSoloOn = computed(() => liveOn.value && !filtersOpen.value && appliedLight.value && filteredCache.value != null);

async function loadProfiles() {
	try { profiles.value = (await api.get('/items/filter_profiles', { params: { fields: ['id', 'name', 'chain'], sort: 'name', limit: 100 } })).data.data ?? []; }
	catch { profiles.value = []; }
}
// Which chain the Lite filtered preview reflects: the editable workChain while the Filters panel is
// open (live tuning + raw|filtered compare), else the op's saved chain when it's light-applied (the
// single filtered pane persists after leaving the panel). Null => nothing to preview.
function previewChain(): FilterChain | null {
	if (filtersOpen.value) return workChain.value;
	if (appliedLight.value && liveOn.value) return savedChain.value;
	return null;
}
let previewAbort: AbortController | null = null;
async function runPreview() {
	const d = detail.value;
	previewAbort?.abort();                     // cancel any in-flight preview (stale-result guard)
	const chain = previewChain();
	if (!d?.live_cache_file || !chain || !chainActive(chain)) { filteredCache.value = null; rawDecimatedCache.value = null; filterFftOverlay.value = null; filterBusy.value = false; return; }
	const ac = new AbortController(); previewAbort = ac;
	filterBusy.value = true; filterErr.value = null;
	try {
		const { cache, skipped, stride } = await fetchFiltered(d.live_cache_file, chain, 1_500_000, ac.signal);
		if (ac.signal.aborted) return;
		filteredCache.value = cache; filterSkipped.value = skipped;
		// Decimate the local full cache by the SAME stride so the raw pane plots the identical
		// samples (honest side-by-side: same geometry, filtered only changes the colour).
		const full = cacheGet(d.live_cache_file);
		rawDecimatedCache.value = full ? decimateCache(full, stride) : null;
		if (chartMode.value === 'fft') filterFftOverlay.value = await fetchFilteredFft(d.live_cache_file, chain, axis.value);
	} catch (e: any) {
		if (e?.name === 'AbortError' || ac.signal.aborted) return;   // superseded — not an error
		filterErr.value = (e?.message || 'filter service unreachable').includes('Failed to fetch')
			? 'filter service unreachable — raw only' : e?.message;
		filteredCache.value = null;
	} finally { if (previewAbort === ac) filterBusy.value = false; }
}
let previewTimer = 0;
watch([workChain, () => detail.value?.live_cache_file, () => filtersOpen.value, () => appliedLight.value, () => liveOn.value, axis, chartMode], () => {
	// Preview whenever we're tuning (panel open) OR the op is light-applied and Lite is showing it.
	if (!filtersOpen.value && !(appliedLight.value && liveOn.value)) {
		if (!compareOn.value) filteredCache.value = null;   // drop the stale filtered cloud
		return;
	}
	clearTimeout(previewTimer);
	previewTimer = window.setTimeout(runPreview, 400);
}, { deep: true });
watch(() => detail.value?.id, () => {
	workChain.value = savedChain.value ?? defaultChain();
	filteredCache.value = null; filterErr.value = null; filterFftOverlay.value = null;
});
function applyProfile(id: string) {
	const p = profiles.value.find((x) => x.id === id);
	if (p?.chain) workChain.value = mergeChain(typeof p.chain === 'string' ? JSON.parse(p.chain) : p.chain);
}
async function saveProfile() {
	const name = window.prompt('Save filter profile as:'); if (!name) return;
	try { await api.post('/items/filter_profiles', { name, chain: workChain.value }); await loadProfiles(); }
	catch (e: any) { filterErr.value = e?.response?.data?.errors?.[0]?.message || 'save failed (name taken?)'; }
}
// Light apply: save the chain as the op's default WITHOUT reprocessing. Lite recomputes it live
// (single filtered pane persists once the Filters panel closes); Full octree & FRM PNGs stay raw
// until an explicit Bake (or the crawler rebuilds). No host daemon needed, not admin-gated.
async function applyFilter() {
	const d = detail.value;
	if (!d?.id || !chainActive(workChain.value)) return;
	const chain = JSON.parse(JSON.stringify(workChain.value));
	filterErr.value = null;
	detail.value = { ...detail.value, filter_chain: chain, filter_baked: false };   // optimistic — solo pane shows now
	try { await api.patch(`/items/machining_force_analysis/${d.id}`, { filter_chain: chain, filter_baked: false }); }
	catch (e: any) { filterErr.value = e?.response?.status === 403 ? 'Not permitted to save this filter.' : (e?.message || 'save failed'); }
	openPanel.value = null;   // close the Filters panel → collapse compare down to the single filtered pane
}
async function bakeFilters() {
	const d = detail.value;
	if (!d?.id || baking.value) return;
	baking.value = true; filterErr.value = null;
	try {
		await api.patch(`/items/machining_force_analysis/${d.id}`, { filter_chain: workChain.value, status: 'pending' });
		const deadline = Date.now() + 15 * 60 * 1000;
		while (Date.now() < deadline) {
			await new Promise((r) => setTimeout(r, 3000));
			const row = (await api.get(`/items/machining_force_analysis/${d.id}`, { params: { fields: ['status', 'filter_chain', 'live_cache_file', 'error_message'] } })).data?.data;
			if (row?.status === 'done') {
				await api.patch(`/items/machining_force_analysis/${d.id}`, { filter_baked: true }).catch(() => {});   // outputs now reprocessed
				detail.value = { ...detail.value, filter_chain: row.filter_chain, filter_baked: true, live_cache_file: row.live_cache_file };
				cachePut(row.live_cache_file, null as any); await loadFrm(); return;
			}
			if (row?.status === 'error') { filterErr.value = `Bake failed: ${row.error_message || 'unknown'}`; return; }
		}
		filterErr.value = 'Still baking — check back shortly (is the force orchestrator running?).';
	} catch (e: any) { filterErr.value = e?.response?.status === 403 ? 'Not permitted (admin only) to bake.' : (e?.message || 'bake request failed'); }
	finally { baking.value = false; }
}
// Clear routes by state: a light apply just drops the saved chain (no host); a bake must reprocess
// the outputs back to raw (status='pending', admin-only), so it keeps the polling path.
async function clearFilter() {
	const d = detail.value; if (!d?.id) return;
	if (!filterBaked.value) {
		workChain.value = defaultChain();
		filteredCache.value = null;
		detail.value = { ...detail.value, filter_chain: null, filter_baked: false };
		await api.patch(`/items/machining_force_analysis/${d.id}`, { filter_chain: null, filter_baked: false }).catch(() => {});
		return;
	}
	await clearBake();
}
async function clearBake() {
	const d = detail.value; if (!d?.id) return;
	workChain.value = defaultChain();
	await api.patch(`/items/machining_force_analysis/${d.id}`, { filter_chain: null, filter_baked: false, status: 'pending' }).catch(() => {});
	baking.value = true;
	try {
		const deadline = Date.now() + 15 * 60 * 1000;
		while (Date.now() < deadline) {
			await new Promise((r) => setTimeout(r, 3000));
			const row = (await api.get(`/items/machining_force_analysis/${d.id}`, { params: { fields: ['status', 'live_cache_file'] } })).data?.data;
			if (row?.status === 'done') { detail.value = { ...detail.value, filter_chain: null, filter_baked: false, live_cache_file: row.live_cache_file }; cachePut(row.live_cache_file, null as any); await loadFrm(); return; }
			if (row?.status === 'error') return;
		}
	} finally { baking.value = false; }
}
// Manual colour-scale limits for the live cloud (null => auto prctile 1/99 in
// liveCloud). autoClimits mirrors what the cloud actually applied so the fields
// can display/seed from the current auto values.
const cauto = ref(true);
const cminManual = ref(0);
const cmaxManual = ref(1);
const autoClimits = ref<{ cmin: number; cmax: number } | null>(null);
const cmin = computed(() => (cauto.value ? null : cminManual.value));
const cmax = computed(() => (cauto.value ? null : cmaxManual.value));
function onClimits(v: { cmin: number; cmax: number }) {
	autoClimits.value = v;
	if (cauto.value) { cminManual.value = Number(v.cmin.toFixed(2)); cmaxManual.value = Number(v.cmax.toFixed(2)); }
}
// Filtering shifts the force range (e.g. a high-pass strips the DC offset), so any manually
// locked colour limits become meaningless — auto-unlock so both panes recompute their own
// scale over the (raw / filtered) data.
watch(() => chainActive(workChain.value), (active) => { if (active) cauto.value = true; });
// In-place collapses to free space when live.
const sampleDetailOpen = ref(true);
const colStackHidden = ref(false);               // hide the Samples/Operations column
const detailHidden = ref(false);                 // hide the Sample/Operation detail column
const frmUrl = ref<string | null>(null);
const frmLoading = ref(false);
const frmCache = new Map<string, string>();

// ---------------------------------------------------------------- layout state
// Column widths + the Force/FRM split are user-resizable (drag handles) and each
// of Force/FRM can be hidden so the other takes the full width. Persisted per
// browser so the layout survives a reload.
const LAYOUT_KEY = 'd1-force-dashboard-layout-v1';
const colA = ref(240);          // Samples/Operations column width (px)
const colB = ref(300);          // Sample/Operation detail column width (px)
const rightSplit = ref(0.46);   // fraction of the right area given to Signals vs FRM
const showForce = ref(true);
const showFRM = ref(true);
const dragging = ref(false);

(function loadLayout() {
	try {
		const raw = localStorage.getItem(LAYOUT_KEY);
		if (!raw) return;
		const v = JSON.parse(raw);
		if (typeof v.colA === 'number') colA.value = v.colA;
		if (typeof v.colB === 'number') colB.value = v.colB;
		if (typeof v.rightSplit === 'number') rightSplit.value = v.rightSplit;
		if (typeof v.showForce === 'boolean') showForce.value = v.showForce;
		if (typeof v.showFRM === 'boolean') showFRM.value = v.showFRM;
		if (typeof v.colStackHidden === 'boolean') colStackHidden.value = v.colStackHidden;
		if (typeof v.detailHidden === 'boolean') detailHidden.value = v.detailHidden;
		if (v.frmMode === 'figure' || v.frmMode === 'lite' || v.frmMode === 'full') frmMode.value = v.frmMode;
	} catch { /* ignore malformed/absent saved layout */ }
})();
watch([colA, colB, rightSplit, showForce, showFRM, colStackHidden, detailHidden, frmMode], () => {
	localStorage.setItem(LAYOUT_KEY, JSON.stringify({
		colA: colA.value, colB: colB.value, rightSplit: rightSplit.value,
		showForce: showForce.value, showFRM: showFRM.value,
		colStackHidden: colStackHidden.value, detailHidden: detailHidden.value,
		// Persist Live so returning to the dashboard keeps the interactive FRM cloud
		// instead of silently dropping back to the static PNG. (liveOn still requires a
		// live cache on the selected op, so ops without one safely show the PNG.)
		frmMode: frmMode.value,
	}));
});

function dragAxis(getStart: () => number, apply: (v: number) => void, min: number, max: number) {
	return (ev: PointerEvent) => {
		ev.preventDefault();
		const startX = ev.clientX;
		const start = getStart();
		dragging.value = true;
		function onMove(e: PointerEvent) { apply(Math.min(max, Math.max(min, start + (e.clientX - startX)))); }
		function onUp() {
			dragging.value = false;
			window.removeEventListener('pointermove', onMove);
			window.removeEventListener('pointerup', onUp);
		}
		window.addEventListener('pointermove', onMove);
		window.addEventListener('pointerup', onUp);
	};
}
const startColAResize = dragAxis(() => colA.value, (v) => { colA.value = v; }, 170, 380);
const startColBResize = dragAxis(() => colB.value, (v) => { colB.value = v; }, 220, 460);

const rightAreaEl = ref<HTMLElement | null>(null);
function startSplitResize(ev: PointerEvent) {
	ev.preventDefault();
	const rect = rightAreaEl.value?.getBoundingClientRect();
	if (!rect) return;
	dragging.value = true;
	function onMove(e: PointerEvent) {
		rightSplit.value = Math.min(0.78, Math.max(0.22, (e.clientX - rect.left) / rect.width));
	}
	function onUp() {
		dragging.value = false;
		window.removeEventListener('pointermove', onMove);
		window.removeEventListener('pointerup', onUp);
	}
	window.addEventListener('pointermove', onMove);
	window.addEventListener('pointerup', onUp);
}

// Below this content width, fixed pixel columns would overflow — stack instead.
// Tracks the real element (Directus reserves side chrome, so the viewport is
// not a reliable proxy).
const layoutEl = ref<HTMLElement | null>(null);
const layoutW = ref(1400);
const stacked = computed(() => layoutW.value < 860);
const gridCols = computed(() => {
	if (stacked.value) return '1fr';
	// COL1 (samples/operations) and COL2 (sample/operation detail) can each be
	// folded away to the left to hand the right area more room. Track list is built
	// positionally to match exactly which columns (+ their resizers) are rendered.
	const parts: string[] = [];
	if (!colStackHidden.value) parts.push(`${colA.value}px`, '6px');
	if (!detailHidden.value) parts.push(`${colB.value}px`, '6px');
	parts.push('1fr');
	return parts.join(' ');
});

// Fit the whole module into the viewport height (no page scroll) on any screen,
// including 16:9 desktops — measured, not guessed, since Directus's own chrome
// height varies. Re-measured on mount + window resize; skipped when stacked
// (mobile/narrow layouts scroll naturally, like any long page).
const availableHeight = ref(700);
function updateAvailableHeight() {
	if (!layoutEl.value) return;
	const top = layoutEl.value.getBoundingClientRect().top;
	availableHeight.value = Math.max(420, Math.floor(window.innerHeight - top - 20));
}
function measureLayout() {
	if (!layoutEl.value) return;
	layoutW.value = layoutEl.value.getBoundingClientRect().width;
	updateAvailableHeight();
}
let layoutRO: ResizeObserver | undefined;
onMounted(() => {
	// ResizeObserver covers content reflow (panel resize, hide/show toggles);
	// a direct window 'resize' listener is a belt-and-braces fallback since RO
	// firing can be unreliable under rapid/programmatic viewport changes.
	layoutRO = new ResizeObserver(measureLayout);
	if (layoutEl.value) layoutRO.observe(layoutEl.value);
	measureLayout();
	window.addEventListener('resize', measureLayout);
});
onBeforeUnmount(() => {
	layoutRO?.disconnect();
	window.removeEventListener('resize', measureLayout);
});

// -------------------------------------------------------------------- data
onMounted(async () => {
	loadProfiles();
	try {
		// Auto-route threshold comes from the crawler's live_cache_points setting.
		try {
			const s = await api.get('/items/force_crawler_state', { params: { fields: ['live_cache_points', 'octree_threshold', 'octree_min_node_px', 'octree_budget_cap'], limit: 1 } });
			const row = s.data?.data?.[0] || s.data?.data;
			const cap = Number(row?.octree_threshold ?? row?.live_cache_points);
			if (Number.isFinite(cap) && cap > 0) octreeThreshold.value = cap;
			const mnp = Number(row?.octree_min_node_px);
			if (Number.isFinite(mnp) && mnp > 0) octreeMinNodePx.value = mnp;
			const bc = Number(row?.octree_budget_cap);
			if (Number.isFinite(bc) && bc > 0) octreeBudgetCap.value = bc;
		} catch { /* keep the 5M fallback */ }
		if (!isAdminRole.value) {
			const uid = (userStore.currentUser as any)?.id;
			if (uid) {
				try {
					const me = await api.get('/items/people', { params: { filter: { user_id: { _eq: uid } }, limit: 1, fields: ['person_id'] } });
					myPersonId.value = me.data?.data?.[0]?.person_id ?? null;
				} catch { myPersonId.value = null; }
			}
		}

		const filter: any = { status: { _eq: 'done' } };
		if (!isAdminRole.value) {
			if (!myPersonId.value) {
				// No linked people row for this account — show nothing rather than
				// accidentally matching rows with a NULL owner via `_eq: null`.
				rows.value = [];
				return;
			}
			// Related to me = I own the sample, own the operation, or ran it.
			filter._and = [{ _or: [
				{ 'operation_id.sample_id.owner_person_id': { _eq: myPersonId.value } },
				{ 'operation_id.owner_person_id': { _eq: myPersonId.value } },
				{ 'operation_id.operator_person_id': { _eq: myPersonId.value } },
			] }];
		}

		const res = await api.get('/items/machining_force_analysis', {
			params: {
				filter,
				limit: -1,
				fields: [
					'id', 'peak_fx', 'peak_fy', 'peak_fz', 'status', 'live_cache_file', 'octree_status',
					'operation_id.operation_id', 'operation_id.pass_code', 'operation_id.operation_date',
					'operation_id.sample_id.sample_id', 'operation_id.sample_id.sample_code',
					'operation_id.sample_id.nickname', 'operation_id.sample_id.material_id.common_name',
					'operation_id.sample_id.owner_person_id.full_name',
				],
			},
		});
		rows.value = res.data.data ?? [];
		// Deep-link: /d1-force-dashboard?operation=<operation_id>, e.g. from the
		// "View Force Analysis" button on the operation form. Falls back to the last
		// selection (persisted) so navigating away and back restores the view.
		const opParam = typeof route.query.operation === 'string'
			? route.query.operation
			: (() => { try { return localStorage.getItem(LAST_OP_KEY) || undefined; } catch { return undefined; } })();
		if (opParam) {
			const match = rows.value.find((r) => r.operation_id?.operation_id === opParam);
			if (match) await selectOp(match);
		}
	} finally {
		loading.value = false;
		// .layout swaps from hidden to visible here; re-measure in case the
		// spinner-to-content swap shifted anything (defensive, cheap).
		await nextTick();
		measureLayout();
	}
});

onBeforeUnmount(() => { for (const u of frmCache.values()) URL.revokeObjectURL(u); });

function sampleOf(r: any) { return r.operation_id?.sample_id; }

// Numeric-aware comparators: "10-AA-MF-..." must sort after "2-AA-MF-..." (the
// leading counter), and "F10" after "F2" (the pass number) — plain string
// compare puts "10" before "2" since only the first character is read.
function leadingInt(s: string | null | undefined): number {
	const m = /^(\d+)/.exec(s || '');
	return m ? parseInt(m[1], 10) : Number.POSITIVE_INFINITY;
}
function passNumber(code: string | null | undefined): number {
	const m = /F(\d+)/i.exec(code || '');
	return m ? parseInt(m[1], 10) : Number.POSITIVE_INFINITY;
}
function bySampleCode(a: any, b: any) {
	const d = leadingInt(a.sample_code) - leadingInt(b.sample_code);
	return d !== 0 ? d : (a.sample_code || '').localeCompare(b.sample_code || '');
}
function byPassCode(a: any, b: any) {
	const ca = a.operation_id?.pass_code, cb = b.operation_id?.pass_code;
	const d = passNumber(ca) - passNumber(cb);
	return d !== 0 ? d : (ca || '').localeCompare(cb || '');
}

const samples = computed(() => {
	const map = new Map<string, any>();
	for (const r of rows.value) {
		const s = sampleOf(r);
		if (!s?.sample_id) continue;
		let e = map.get(s.sample_id);
		if (!e) {
			e = { sample_id: s.sample_id, sample_code: s.sample_code, nickname: s.nickname,
				material: s.material_id?.common_name, owner: s.owner_person_id?.full_name, ops: [] as any[] };
			map.set(s.sample_id, e);
		}
		e.ops.push(r);
	}
	const arr = [...map.values()];
	arr.sort(bySampleCode);
	return arr;
});

const filteredSamples = computed(() => {
	const q = sampleSearch.value.trim().toLowerCase();
	return q ? samples.value.filter((s) =>
		(s.sample_code || '').toLowerCase().includes(q) || (s.nickname || '').toLowerCase().includes(q)
		|| (s.material || '').toLowerCase().includes(q)) : samples.value;
});

// Data-quality stoplight for an operation row (mirrors the FAST dashboard). Green = a
// plottable FRM cache exists · Blue = processing · Yellow = octree-only (no live cache) ·
// Red = failed or no plot data.
function frmQuality(o: any): { level: string; label: string } {
	if (o?.status === 'pending' || o?.status === 'processing') return { level: 'blue', label: 'Processing…' };
	if (o?.live_cache_file) return { level: 'green', label: 'FRM plot ready' };
	if (o?.octree_status === 'done') return { level: 'yellow', label: 'Octree only (no live cache)' };
	if (o?.status === 'error') return { level: 'red', label: 'Processing failed' };
	return { level: 'red', label: 'No plot data' };
}

const displayedOps = computed(() => {
	let list = filterSampleId.value
		? rows.value.filter((r) => sampleOf(r)?.sample_id === filterSampleId.value)
		: rows.value.slice();
	const q = opSearch.value.trim().toLowerCase();
	if (q) list = list.filter((r) =>
		(r.operation_id?.pass_code || '').toLowerCase().includes(q)
		|| (sampleOf(r)?.sample_code || '').toLowerCase().includes(q));
	return list.sort(byPassCode);
});

const selectedSample = computed(() => samples.value.find((s) => s.sample_id === selectedSampleId.value) || null);

function selectSample(s: any) {
	if (filterSampleId.value === s.sample_id) {
		filterSampleId.value = null;
		selectedSampleId.value = null;
		return;
	}
	filterSampleId.value = s.sample_id;
	selectedSampleId.value = s.sample_id;
	if (detail.value && sampleOf(detail.value)?.sample_id !== s.sample_id) {
		selectedRowId.value = null; detail.value = null; frmUrl.value = null;
	}
}

const LAST_OP_KEY = 'd1-force-dashboard-lastop';
async function selectOp(row: any) {
	selectedRowId.value = row.id;
	selectedSampleId.value = sampleOf(row)?.sample_id ?? null;
	// Remember the selection so navigating away and back restores it.
	try { const opId = row.operation_id?.operation_id; if (opId) localStorage.setItem(LAST_OP_KEY, opId); } catch { /* ignore */ }
	loadingDetail.value = true;
	detail.value = null;
	frmUrl.value = null;
	try {
		const res = await api.get(`/items/machining_force_analysis/${row.id}`, {
			params: {
				fields: ['*',
					'operation_id.operation_id', 'operation_id.pass_code', 'operation_id.operation_date',
					'operation_id.operation_sequence', 'operation_id.machining_operation_subtype',
					'operation_id.process_category', 'operation_id.operator_name',
					'operation_id.machining_new_edge', 'operation_id.machining_coolant_used', 'operation_id.outcome_notes',
					'operation_id.equipment_id.equipment_name', 'operation_id.method_id.method_name',
					'operation_id.sample_id.sample_id', 'operation_id.sample_id.sample_code', 'operation_id.sample_id.nickname',
					'operation_id.sample_id.form', 'operation_id.sample_id.manufactured_date',
					'operation_id.sample_id.owner_person_id.full_name',
					'operation_id.sample_id.material_id.common_name',
					'directus_files_id.filesize', 'live_cache_file', 'live_render_points', 'pulses_per_rev', 'inner_diameter', 'outer_diameter', 'filter_chain', 'filter_baked',
					'octree_status', 'octree_path', 'octree_points',
					'grid_octree_status', 'grid_octree_path', 'grid_octree_points',
					'grid_fidelity', 'grid_arm_ratio', 'grid_cell_mm'],
			},
		});
		detail.value = res.data.data;
		editPpr.value = Number(detail.value?.pulses_per_rev) || 1;
		await loadFrm();
	} finally {
		loadingDetail.value = false;
	}
}

async function loadFrm() {
	const d = detail.value;
	if (!d) { frmUrl.value = null; return; }
	const fileId = d[`frm_${axis.value.toLowerCase()}`];
	if (!fileId) { frmUrl.value = null; return; }
	if (frmCache.has(fileId)) { frmUrl.value = frmCache.get(fileId)!; return; }
	frmLoading.value = true;
	try {
		const res = await api.get(`/assets/${fileId}`, { responseType: 'blob' });
		const url = URL.createObjectURL(res.data);
		frmCache.set(fileId, url);
		frmUrl.value = url;
	} catch { frmUrl.value = null; } finally { frmLoading.value = false; }
}
function setAxis(a: Axis) { axis.value = a; loadFrm(); }

const op = computed(() => detail.value?.operation_id ?? null);
const opSample = computed(() => op.value?.sample_id ?? null);
const opLabel = computed(() => op.value?.pass_code || opSample.value?.sample_code || '—');

// Sample info: rich from the loaded operation, else the light list row.
const sampleInfo = computed(() => {
	if (opSample.value) {
		const s = opSample.value;
		return { id: s.sample_id, sample_code: s.sample_code, material: s.material_id?.common_name,
			nickname: s.nickname, form: s.form, owner: s.owner_person_id?.full_name,
			manufactured: s.manufactured_date, ops: samples.value.find((x) => x.sample_id === s.sample_id)?.ops.length };
	}
	if (selectedSample.value) {
		const s = selectedSample.value;
		return { id: s.sample_id, sample_code: s.sample_code, material: s.material, nickname: s.nickname, owner: s.owner, ops: s.ops.length };
	}
	return null;
});

const opMeta = computed(() => {
	const o = op.value;
	if (!o) return [];
	return [
		['Date', fmtDate(o.operation_date)],
		['Recorded', fmtDateTime(detail.value?.trigger_time)],
		['Machine', o.equipment_id?.equipment_name],
		['Method', o.method_id?.method_name],
		['Subtype', o.machining_operation_subtype],
		['Sequence', o.operation_sequence != null ? `#${o.operation_sequence}` : null],
		['New edge', o.machining_new_edge == null ? null : (o.machining_new_edge ? 'Yes' : 'No')],
		['Coolant', o.machining_coolant_used == null ? null : (o.machining_coolant_used ? 'Yes' : 'No')],
		['Operator', o.operator_name],
	].filter(([, v]) => v != null && v !== '');
});

function fmtBytes(n: number | null | undefined): string {
	if (!n) return '—';
	if (n >= 1e9) return `${(n / 1e9).toFixed(2)} GB`;
	if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
	if (n >= 1e3) return `${(n / 1e3).toFixed(0)} kB`;
	return `${n} B`;
}
function fmtCutTime(d: any): string {
	if (!d?.sample_rate || d.cut_start_idx == null || d.cut_end_idx == null) return '—';
	const secs = (d.cut_end_idx - d.cut_start_idx) / d.sample_rate;
	if (secs >= 60) return `${Math.floor(secs / 60)}m ${Math.round(secs % 60)}s`;
	return `${secs.toFixed(1)}s`;
}

// Cut parameters: how the operation was set up + what it measured. Shown in BOTH view
// modes (previously they vanished the moment Lite was on — reference data shouldn't
// depend on an unrelated display toggle).
const cutParams = computed(() => {
	const d = detail.value;
	if (!d) return [];
	const mrpm = d.mean_rpm != null ? Number(d.mean_rpm).toFixed(0) : '—';
	return [
		{ label: 'Surface speed', value: fmt(d.surface_speed), unit: 'm/min' },
		{ label: 'Feed', value: fmt(d.feed), unit: 'mm/rev' },
		{ label: 'Depth of cut', value: fmt(d.depth_of_cut), unit: 'mm' },
		{ label: 'Diameter', value: fmt(d.cut_diameter), unit: 'mm' },
		{ label: 'Mean RPM', value: mrpm, unit: '' },
		{ label: 'Cut time', value: fmtCutTime(d), unit: '' },
	];
});
// Capture/technical info: rarely needed at a glance -> its own collapsed accordion.
const captureInfo = computed(() => {
	const d = detail.value;
	if (!d) return [];
	return [
		['Sample rate', d.sample_rate ? `${(d.sample_rate / 1000).toFixed(1)} kHz` : '—'],
		['Dyno gain', d.dyno_gain != null ? `${fmt(d.dyno_gain)} N/V` : '—'],
		['Pulses/rev', d.pulses_per_rev != null ? String(d.pulses_per_rev) : '—'],
		['Raw points', d.n_raw != null ? Number(d.n_raw).toLocaleString() : '—'],
		['File version', d.file_version != null ? String(d.file_version) : '—'],
		['File size', fmtBytes(d.directus_files_id?.filesize)],
	].filter(([, v]) => v !== '—') as [string, string][];
});
// Accordion state for the reworked op panel (persist nothing; sensible defaults).
const captureOpen = ref(false);
const displayOpen = ref(false);
const hostOpen = ref(false);

const showRpm = ref(false);

// Entering Live collapses the sample detail + the op's date/coolant rows to free
// vertical space for the crop plots, cloud, and plotting-settings panel.
watch(frmMode, (m) => { sampleDetailOpen.value = m !== 'lite'; if (m === 'lite') chartMode.value = 'force'; });
// Live needs a loaded cache; if this op has none, fall back to the static view.
const liveAvailable = computed(() => !!detail.value?.live_cache_file);
const liveOn = computed(() => frmMode.value === 'lite' && liveAvailable.value);

// The window that actually feeds the FRM map (cut_start_idx..cut_end_idx into
// the raw signal); converted to seconds so ForceChart can shade it in vs. the
// discarded lead-in/out at lower saturation.
const cropWindow = computed(() => {
	const d = detail.value;
	if (!d || !d.sample_rate || d.cut_start_idx == null || d.cut_end_idx == null) return null;
	return { start: d.cut_start_idx / d.sample_rate, end: d.cut_end_idx / d.sample_rate };
});

// Live and the chart mode (Force/FFT) are independent: Live drives the FRM cloud +
// editable crop, while the signal graphs can still be flipped to FFT. The crop
// range the force plots shade/drag is the live editable one when Live is on.
const effectiveMode = computed(() => chartMode.value);
const activeCrop = computed(() => (liveOn.value
	? { start: cropStartSec.value, end: cropEndSec.value }
	: cropWindow.value));
// When live, drop the date/coolant-ish rows to free space (keep the essentials).
const HIDE_WHEN_LIVE = new Set(['Date', 'Recorded', 'Coolant', 'New edge', 'Sequence']);
const compactMeta = computed(() => (liveOn.value ? opMeta.value.filter((m) => !HIDE_WHEN_LIVE.has(m[0] as string)) : opMeta.value));

const PEAK_FIELD: Record<string, string> = { Fx: 'peak_fx', Fy: 'peak_fy', Fz: 'peak_fz' };
const charts = computed(() => {
	const d = detail.value;
	const base = AXES.map((a) => (
		effectiveMode.value === 'force'
			? { key: a, title: `${a} · force`, kind: 'env' as const, data: d?.series?.[a], color: AXIS_COLOR[a], xUnit: 's', yUnit: 'N',
				cropStart: activeCrop.value?.start, cropEnd: activeCrop.value?.end, peak: d?.[PEAK_FIELD[a]] }
			: { key: a, title: `${a} · spectrum`, kind: 'line' as const, data: d?.fft?.[a], color: AXIS_COLOR[a], xUnit: 'Hz', yUnit: '', logY: true }
	));
	if (effectiveMode.value === 'force' && showRpm.value) {
		base.push({ key: 'RPM', title: 'RPM', kind: 'env', data: detail.value?.series?.RPM, color: '#a855f7', xUnit: 's', yUnit: 'rpm',
			cropStart: activeCrop.value?.start, cropEnd: activeCrop.value?.end } as any);
	}
	return base;
});

// Seed the editable controls from the loaded cache (FrmCloud emits this once the
// binary is parsed). User edits thereafter drive the cloud; Reset restores these.
function onCloudLoaded(meta: { csSec: number; ceSec: number; feed: number; diam: number; rpm: number; Fs: number; N: number }) {
	cropStartSec.value = meta.csSec;
	cropEndSec.value = meta.ceSec;
	editFeed.value = cleanFloat(meta.feed);
	editDiam.value = cleanFloat(meta.diam);
	const od = Number(detail.value?.outer_diameter);
	if (od > 0) editDiam.value = od;   // per-op override beats the cache header
	editRpm.value = meta.rpm;
	editRate.value = meta.Fs;
	cacheFs = meta.Fs;
	speedMode.value = 'measured';
	// derive a sensible Vc default from the measured mean speed + diameter
	editVc.value = Math.round(Math.PI * meta.diam * meta.rpm / 1000) || 100;
	// the cache's feed/diam/rate are the "source" for the modified-highlight in Live
	srcCut.feed = editFeed.value; srcCut.diam = editDiam.value; srcCut.rate = editRate.value;
}
function resetLive() {
	const d = detail.value;
	if (cropWindow.value) { cropStartSec.value = cropWindow.value.start; cropEndSec.value = cropWindow.value.end; }
	if (d) {
		editFeed.value = Number(d.feed) || editFeed.value;
		editDiam.value = Number(d.outer_diameter) || Number(d.cut_diameter) || editDiam.value;
		editInnerDiam.value = Number(d.inner_diameter) || 0;
		editRate.value = Number(d.sample_rate) || editRate.value;
		editPpr.value = Number(d.pulses_per_rev) || 1;
	}
	speedMode.value = 'measured';
	plotStride.value = 1; gridding.value = false; pointSize.value = 1.4; colormap.value = 'viridis';
	cauto.value = true;
}
// Rate override rescales time for the constant-RPM/Vc models (measured mode uses the
// baked revs, so it's unaffected). timeScale = 1 when Rate is left at the cache's Fs.
const timeScale = computed(() => (editRate.value > 0 ? cacheFs / editRate.value : 1));

// Tier 2: ask the host to regenerate the cache at a finer resolution (down to 1:1).
async function processFullRes() {
	const d = detail.value;
	if (!d?.id || rendering.value) return;
	rendering.value = true;
	renderMsg.value = 'Requesting host render…';
	try {
		await api.patch(`/items/machining_force_analysis/${d.id}`, {
			status: 'pending', live_render_points: Math.max(1, Math.round(renderPoints.value)),
		});
		renderMsg.value = 'Queued — waiting for the host crawler…';
		await pollRender(d.id, d.live_cache_file);
	} catch (e: any) {
		renderMsg.value = e?.response?.status === 403
			? 'Not permitted (admin only) to request a host render.'
			: (e?.message || 'render request failed');
	} finally {
		rendering.value = false;
	}
}
async function pollRender(id: string, prevCacheId: string | null) {
	const deadline = Date.now() + 5 * 60 * 1000;         // give the host up to 5 min
	while (Date.now() < deadline) {
		await new Promise((r) => setTimeout(r, 2500));
		let row: any = null;
		try {
			const res = await api.get(`/items/machining_force_analysis/${id}`, { params: { fields: ['status', 'live_cache_file', 'live_render_points', 'error_message'] } });
			row = res.data?.data;
		} catch { /* transient */ }
		if (!row) continue;
		if (row.status === 'error') { renderMsg.value = `Host render failed: ${row.error_message || 'unknown error'}`; return; }
		if (row.status === 'done' && !row.live_render_points) {
			renderMsg.value = 'Rendered at requested resolution.';
			if (detail.value && detail.value.id === id) detail.value = { ...detail.value, live_cache_file: row.live_cache_file };
			return;
		}
	}
	renderMsg.value = 'Still processing on the host — check back shortly.';
}

function openSampleForm() { if (sampleInfo.value?.id) router.push(`/content/physical_samples/${sampleInfo.value.id}`); }
function openOpForm() { if (op.value?.operation_id) router.push(`/content/manufacturing_operations/${op.value.operation_id}`); }

function fmt(v: any): string {
	if (v == null || v === '') return '—';
	const n = Number(v);
	return Number.isFinite(n) ? (Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(2)) : '—';
}
// Strip float32 round-trip noise (the live cache stores feed/diam as float32, so they
// read back as 0.10000000149… ). toPrecision(6) collapses that to 0.1 while KEEPING
// genuine sub-values like 0.017 — so this is safer than a blunt toFixed(2), which would
// wrongly flatten 0.017 → 0.02.
function cleanFloat(v: any): number {
	const n = Number(v);
	return Number.isFinite(n) ? parseFloat(n.toPrecision(6)) : (v as number);
}
function fmtDate(v: string) {
	return v ? new Date(v).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '';
}
// In-app download: /assets/<id>?download forces a save (same-origin, authed by cookie).
function downloadFile(fileId: string) {
	const a = document.createElement('a');
	a.href = `/assets/${fileId}?download`;
	a.rel = 'noopener';
	document.body.appendChild(a); a.click(); a.remove();
}

// "Download this FRM image": in an interactive view (live cloud or octree) export the CURRENT
// viewport — whatever zoom/pan is on screen — straight from the canvas. Only the static image
// view (no interactive renderer) falls back to the precomputed full-scale PNG.
const frmOctreeRef = ref<any>(null);
function downloadFrm() {
	const d = detail.value;
	if (!d) return;
	const label = String((opLabel.value && opLabel.value !== '—') ? opLabel.value : (d.operation_code || d.operation_id || d.id));
	const name = `FRM_${axis.value}_${label}.png`;
	if (octreeOn.value && frmOctreeRef.value?.exportViewport) { if (frmOctreeRef.value.exportViewport(name, label)) return; }
	if (liveOn.value && frmCloudRef.value?.exportViewport) { if (frmCloudRef.value.exportViewport(name, label)) return; }
	const f = d[`frm_${axis.value.toLowerCase()}`];
	if (f) downloadFile(f);
}

// Template ref to the live cloud, used by downloadFrm() to export the current viewport.
const frmCloudRef = ref<any>(null);
// The .mat file's own metadata.TriggerTime, when present — the actual recording
// time, as distinct from operation_date (often just the sample record's creation
// time for legacy imports).
function fmtDateTime(v: string | null | undefined) {
	if (!v) return '';
	const d = new Date(v);
	if (Number.isNaN(d.getTime())) return '';
	return d.toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}
</script>

<template>
	<private-view title="Force Analysis">
		<div class="fd">
			<section class="hero">
				<span class="hero-badge"><v-icon name="insights" x-small /> Force Analysis</span>
				<span class="hero-stat">{{ rows.length }} op{{ rows.length === 1 ? '' : 's' }} · {{ samples.length }} sample{{ samples.length === 1 ? '' : 's' }}</span>
				<div class="hero-spacer"></div>
				<div class="panel-toggles">
					<span class="pt-label">Panels</span>
					<button class="pt-chip" :class="{ on: showForce }" :disabled="showForce && !showFRM"
						@click="showForce = !showForce">
						<v-icon :name="showForce ? 'visibility' : 'visibility_off'" x-small /> Force / FFT
					</button>
					<button class="pt-chip" :class="{ on: showFRM }" :disabled="showFRM && !showForce"
						@click="showFRM = !showFRM">
						<v-icon :name="showFRM ? 'visibility' : 'visibility_off'" x-small /> FRM map
					</button>
				</div>
			</section>

			<div v-show="loading" class="loading"><v-progress-circular indeterminate /></div>

			<div v-show="!loading" ref="layoutEl" class="layout" :class="{ dragging, stacked }"
				:style="{ gridTemplateColumns: gridCols, height: stacked ? 'auto' : availableHeight + 'px' }">
				<!-- COL 1: samples + operations (collapsible away to the right) -->
				<div v-if="stacked || !colStackHidden" class="col-stack">
					<div class="panel panel-samples">
						<div class="panel-head"><v-icon name="science" small /><span>Samples</span><span class="chip">{{ filteredSamples.length }}</span>
							<button v-if="!stacked" class="collapsebtn" title="Hide the samples/operations column" @click="colStackHidden = true"><v-icon name="chevron_left" x-small /></button>
						</div>
						<input v-model="sampleSearch" class="search" placeholder="Search samples…" />
						<div class="list">
							<button v-for="s in filteredSamples" :key="s.sample_id"
								class="rowcard" :class="{ active: selectedSampleId === s.sample_id }" @click="selectSample(s)">
								<span class="mono">{{ s.sample_code }}</span>
								<span class="sub">{{ s.material || '—' }}<template v-if="s.nickname"> · {{ s.nickname }}</template></span>
								<span class="pill">{{ s.ops.length }} op{{ s.ops.length === 1 ? '' : 's' }}</span>
							</button>
							<div v-if="!filteredSamples.length" class="empty">No samples</div>
						</div>
					</div>

					<div class="panel panel-ops">
						<div class="panel-head">
							<v-icon name="build" small /><span>Operations</span><span class="chip">{{ displayedOps.length }}</span>
							<button v-if="filterSampleId" class="clearbtn" @click="filterSampleId = null">all</button>
						</div>
						<input v-model="opSearch" class="search" placeholder="Search operations…" />
						<div class="list">
							<button v-for="o in displayedOps" :key="o.id"
								class="rowcard" :class="{ active: selectedRowId === o.id }" @click="selectOp(o)">
								<span class="mono sm"><span class="qdot" :class="frmQuality(o).level" :title="frmQuality(o).label"></span>{{ o.operation_id?.pass_code || '—' }}</span>
								<span class="sub">
									<template v-if="!filterSampleId">{{ sampleOf(o)?.sample_code }} · </template>
									{{ fmtDate(o.operation_id?.operation_date) }}
								</span>
								<span class="badge" :style="{ background: AXIS_COLOR.Fz }">Fz {{ fmt(o.peak_fz) }} N</span>
							</button>
							<div v-if="!displayedOps.length" class="empty">No operations</div>
						</div>
					</div>
				</div>

				<div v-if="!stacked && !colStackHidden" class="resizer" @pointerdown="startColAResize" title="Drag to resize"></div>

				<!-- COL 2: sample detail + operation detail (foldable away to the left) -->
				<div v-if="stacked || !detailHidden" class="col-stack">
					<div class="card info" :class="{ collapsed: !sampleDetailOpen }">
						<div class="info-head">
							<span>
								<button class="chevbtn" title="Collapse/expand" @click="sampleDetailOpen = !sampleDetailOpen"><v-icon :name="sampleDetailOpen ? 'expand_more' : 'chevron_right'" x-small /></button>
								<v-icon name="science" x-small /> Sample detail
							</span>
							<span class="ih-actions">
								<button v-if="sampleInfo?.id" class="openbtn" @click="openSampleForm">Open <v-icon name="open_in_new" x-small /></button>
								<button v-if="!stacked" class="collapsebtn" title="Hide the detail column" @click="detailHidden = true"><v-icon name="chevron_left" x-small /></button>
							</span>
						</div>
						<template v-if="sampleDetailOpen">
							<template v-if="sampleInfo">
								<div class="info-code mono">{{ sampleInfo.sample_code }}</div>
								<div class="kv">
									<span>Material</span><span>{{ sampleInfo.material || '—' }}</span>
									<span>Nickname</span><span>{{ sampleInfo.nickname || '—' }}</span>
									<template v-if="sampleInfo.form"><span>Form</span><span>{{ sampleInfo.form }}</span></template>
									<span>Owner</span><span>{{ sampleInfo.owner || '—' }}</span>
									<template v-if="sampleInfo.manufactured"><span>Made</span><span>{{ fmtDate(sampleInfo.manufactured) }}</span></template>
									<span>Analysed ops</span><span>{{ sampleInfo.ops ?? '—' }}</span>
								</div>
							</template>
							<div v-else class="empty sm">Select a sample or operation</div>
						</template>
					</div>

					<div class="card info info-op" :class="{ collapsed: !opDetailOpen }">
						<div class="info-head">
							<span>
								<button class="chevbtn" title="Collapse/expand" @click="togglePanel('detail')"><v-icon :name="opDetailOpen ? 'expand_more' : 'chevron_right'" x-small /></button>
								<v-icon name="build" x-small /> Operation detail
							</span>
							<button v-if="op?.operation_id" class="openbtn" @click="openOpForm">Open <v-icon name="open_in_new" x-small /></button>
						</div>
						<template v-if="detail && opDetailOpen">
							<div class="info-code mono">{{ opLabel }}</div>
							<div v-if="compactMeta.length" class="kv">
								<template v-for="m in compactMeta" :key="m[0]"><span>{{ m[0] }}</span><span>{{ m[1] }}</span></template>
							</div>

							<!-- Editable cut-parameter boxes (Feed/Diameter/Inner Ø/PPR): drive the Live plot
							     and are threaded into any host bake. Measured values stay read-only. A box is
							     highlighted when its value differs from what the op was loaded with. -->
							<div class="stat-sep">Cut parameters
								<button v-if="!near(editFeed, srcCut.feed) || !near(editDiam, srcCut.diam) || !near(editInnerDiam, srcCut.inner) || !near(editPpr, srcCut.ppr)"
									class="linkbtn" @click="seedCutFromDetail">Reset</button>
							</div>
							<div class="statgrid">
								<div class="stat edit" :class="{ modified: !near(editFeed, srcCut.feed) }">
									<div class="s-top"><input class="s-inp" v-model.number="editFeed" type="number" step="0.01" min="0" /><span class="s-unit">mm/rev</span></div>
									<span class="s-lab">Feed</span>
								</div>
								<div class="stat edit" :class="{ modified: !near(editDiam, srcCut.diam) }">
									<div class="s-top"><input class="s-inp" v-model.number="editDiam" type="number" step="1" min="0" /><span class="s-unit">mm</span></div>
									<span class="s-lab">Diameter</span>
								</div>
								<div class="stat edit" :class="{ modified: !near(editInnerDiam, srcCut.inner) }">
									<div class="s-top"><input class="s-inp" v-model.number="editInnerDiam" type="number" step="1" min="0" title="Donut/diaphragm inner diameter — the spiral stops here. 0 = solid disc." /><span class="s-unit">mm</span></div>
									<span class="s-lab">Inner Ø</span>
								</div>
								<div class="stat edit" :class="{ modified: !near(editPpr, srcCut.ppr) }">
									<div class="s-top"><input class="s-inp" v-model.number="editPpr" type="number" step="1" min="1" /></div>
									<span class="s-lab">Pulses/rev</span>
								</div>
								<div class="stat"><div class="s-top"><span class="s-val">{{ fmt(detail.surface_speed) }}</span><span class="s-unit">m/min</span></div><span class="s-lab">Surface speed</span></div>
								<div class="stat"><div class="s-top"><span class="s-val">{{ fmt(detail.depth_of_cut) }}</span><span class="s-unit">mm</span></div><span class="s-lab">Depth of cut</span></div>
								<div class="stat edit" :class="{ modified: !near(editRate, srcCut.rate) }">
									<div class="s-top"><input class="s-inp" v-model.number="editRateKHz" type="number" step="0.1" min="0.1" /><span class="s-unit">kHz</span></div>
									<span class="s-lab">Capture</span>
								</div>
								<div class="stat"><div class="s-top"><span class="s-val">{{ fmtCutTime(detail) }}</span></div><span class="s-lab">Cut time</span></div>
							</div>

							<template v-if="liveOn">
								<div class="stat-sep">Plot model <span class="u">(what-if — plot only)</span> <button class="linkbtn" @click="resetLive">Reset</button></div>
								<div class="edit-grid">
									<label class="wide">Spindle speed
										<div class="speed-row">
											<select v-model="speedMode">
												<option value="measured">Measured (tacho)</option>
												<option value="rpm">Constant RPM</option>
												<option value="vc">Constant Vc</option>
											</select>
											<input v-if="speedMode === 'rpm'" v-model.number="editRpm" type="number" step="10" min="1" title="RPM" />
											<input v-if="speedMode === 'vc'" v-model.number="editVc" type="number" step="1" min="1" title="Vc (m/min)" />
										</div>
									</label>
								</div>
							</template>

							<button class="acc-head" @click="captureOpen = !captureOpen">
								<v-icon :name="captureOpen ? 'expand_more' : 'chevron_right'" x-small /> Capture
							</button>
							<div v-if="captureOpen && captureInfo.length" class="kv">
								<template v-for="m in captureInfo" :key="m[0]"><span>{{ m[0] }}</span><span>{{ m[1] }}</span></template>
							</div>
						</template>
						<div v-else-if="opDetailOpen && loadingDetail" class="loading sm"><v-progress-circular indeterminate small /></div>
						<div v-else-if="opDetailOpen && !detail" class="empty sm">Select an operation</div>
					</div>

					<!-- Display: appearance of the FRM plot (colour map / point size / colour limits /
					     thinning) + the on-demand host full-res render. Its own accordion so it isn't
					     buried inside the operation detail. -->
					<div v-if="detail" class="card info info-display" :class="{ collapsed: !displayPanelOpen }">
						<div class="info-head">
							<span>
								<button class="chevbtn" title="Collapse/expand" @click="togglePanel('display')"><v-icon :name="displayPanelOpen ? 'expand_more' : 'chevron_right'" x-small /></button>
								<v-icon name="palette" x-small /> Display
							</span>
						</div>
						<template v-if="displayPanelOpen">
							<div class="edit-grid">
								<label>Colour<select v-model="colormap"><option value="viridis">viridis</option><option value="inferno">inferno</option><option value="grayscale">grayscale</option></select></label>
								<label>Point size<input v-model.number="pointSize" type="number" step="0.2" min="0.4" max="6" /></label>
								<label v-if="liveOn">Show every<select v-model.number="plotStride"><option :value="1">all pts</option><option :value="2">2nd</option><option :value="5">5th</option><option :value="10">10th</option><option :value="25">25th</option></select></label>
								<label class="chk wide"><input v-model="cauto" type="checkbox" /> Auto colour limits <span class="u">(prctile 1 / 99)</span></label>
								<label>Colour min <span class="u">N</span><input v-model.number="cminManual" type="number" step="1" :disabled="cauto" /></label>
								<label>Colour max <span class="u">N</span><input v-model.number="cmaxManual" type="number" step="1" :disabled="cauto" /></label>
							</div>
							<template v-if="liveOn">
								<div class="stat-sep">Full-resolution render (host)</div>
								<div class="render-row">
									<label>Points<input v-model.number="renderPoints" type="number" step="50000" min="1000" /></label>
									<button class="processbtn" :disabled="rendering" @click="processFullRes">
										<v-icon :name="rendering ? 'hourglass_top' : 'memory'" x-small /> {{ rendering ? 'Rendering…' : 'Process' }}
									</button>
								</div>
								<div v-if="renderMsg" class="render-msg">{{ renderMsg }}</div>
							</template>
						</template>
					</div>

					<!-- Signal statistics: collapsed by default; computed client-side from the live
					     cache (crop-window force stats + whole-signal bit-depth / clipping analysis). -->
					<div v-if="detail" class="card info info-stats" :class="{ collapsed: !statsOpen }">
						<div class="info-head">
							<span>
								<button class="chevbtn" title="Collapse/expand" @click="togglePanel('stats')"><v-icon :name="statsOpen ? 'expand_more' : 'chevron_right'" x-small /></button>
								<v-icon name="query_stats" x-small /> Signal statistics
							</span>
							<span v-if="sigStats" class="stats-win mono">{{ sigStats.windowSec[0].toFixed(1) }}–{{ sigStats.windowSec[1].toFixed(1) }} s</span>
						</div>
						<template v-if="statsOpen">
							<div v-if="!detail.live_cache_file" class="empty sm">No signal cache — reprocess this op to enable statistics</div>
							<div v-else-if="statsBusy" class="loading sm"><v-progress-circular indeterminate small /> computing…</div>
							<div v-else-if="statsErr" class="render-msg">{{ statsErr }}</div>
							<template v-else-if="sigStats">
								<table class="stats-table">
									<thead><tr><th></th><th>Fx</th><th>Fy</th><th>Fz</th></tr></thead>
									<tbody>
										<tr><td>Mean <span class="u">N</span></td><td v-for="a in STAT_AXES" :key="'m'+a">{{ fmtStat(sigStats.axes[a].mean) }}</td></tr>
										<tr><td>RMS <span class="u">N</span></td><td v-for="a in STAT_AXES" :key="'r'+a">{{ fmtStat(sigStats.axes[a].rms) }}</td></tr>
										<tr><td>Std <span class="u">N</span></td><td v-for="a in STAT_AXES" :key="'s'+a">{{ fmtStat(sigStats.axes[a].std) }}</td></tr>
										<tr><td>Min / Max <span class="u">N</span></td><td v-for="a in STAT_AXES" :key="'x'+a">{{ fmtStat(sigStats.axes[a].min) }} / {{ fmtStat(sigStats.axes[a].max) }}</td></tr>
										<tr><td>Dyn. range <span class="u">bits</span></td><td v-for="a in STAT_AXES" :key="'b'+a">{{ sigStats.axes[a].effBits?.toFixed(1) ?? '—' }}</td></tr>
										<tr><td>Rail hits <span class="u">lo/hi %</span></td><td v-for="a in STAT_AXES" :key="'c'+a">
											<span :class="{ 'stat-bad': sigStats.axes[a].clipped }">{{ sigStats.axes[a].railLoPct.toFixed(2) }} / {{ sigStats.axes[a].railHiPct.toFixed(2) }}<template v-if="sigStats.axes[a].clipped"> ⚠ clip</template></span>
										</td></tr>
									</tbody>
								</table>
								<p class="setting-note">Force stats over the crop window; bits + rails over the whole cached signal. Dyn. range = log2(signal span ÷ noise floor); a clean full-range 12-bit capture sits near ~12–13, well below = under-ranged. Sustained rail hits = clipped / over-ranged.</p>
								<div class="kv stats-rpm"><span>RPM (window)</span><span>{{ fmtStat(sigStats.rpm.mean) }} ± {{ fmtStat(sigStats.rpm.std) }} <span class="u">({{ fmtStat(sigStats.rpm.min) }}–{{ fmtStat(sigStats.rpm.max) }})</span></span></div>
							</template>
							<button v-else class="processbtn stats-compute" :disabled="statsBusy" @click="computeStats">
								<v-icon name="calculate" x-small /> Compute<template v-if="statsCacheMb"> (downloads ~{{ statsCacheMb }} MB signal cache)</template>
							</button>
						</template>
					</div>

					<!-- Signal filters: interactive preview in Lite (raw|filtered compare), bake to
					     apply the chain to every output. Collapsed by default. -->
					<div v-if="detail" class="card info info-filters" :class="{ collapsed: !filtersOpen }">
						<div class="info-head">
							<span>
								<button class="chevbtn" title="Collapse/expand" @click="togglePanel('filters')"><v-icon :name="filtersOpen ? 'expand_more' : 'chevron_right'" x-small /></button>
								<v-icon name="filter_alt" x-small /> Signal filters
							</span>
							<span v-if="bakedChain" class="frm-fid good" title="This op's outputs are baked with a filter chain">baked</span>
							<span v-else-if="appliedLight" class="frm-fid" title="Saved as this op's default — Lite recomputes it live; Full & FRM PNG stay raw until you Bake">applied · Lite</span>
						</div>
						<template v-if="filtersOpen">
							<div v-if="!detail.live_cache_file" class="empty sm">No signal cache — reprocess this op to enable filtering</div>
							<template v-else>
								<div v-if="!liveOn" class="setting-note">Switch to <b>Lite</b> to preview filters side-by-side. You can still edit + bake here.</div>
								<div class="filt-row"><label class="chk"><input v-model="workChain.despike.on" type="checkbox" /> Despike</label>
									<template v-if="workChain.despike.on"><input v-model.number="workChain.despike.window" type="number" min="3" step="2" title="window (odd)" /><input v-model.number="workChain.despike.sigma" type="number" min="1" step="0.5" title="σ" /></template></div>
								<div class="filt-row"><label class="chk"><input v-model="workChain.detrend.on" type="checkbox" /> Detrend</label>
									<template v-if="workChain.detrend.on"><select v-model="workChain.detrend.mode"><option value="highpass">high-pass</option><option value="dc">DC</option></select><input v-if="workChain.detrend.mode==='highpass'" v-model.number="workChain.detrend.cutoff_hz" type="number" min="0.1" step="1" title="cutoff Hz" /></template></div>
								<div class="filt-row"><label class="chk"><input v-model="workChain.highpass.on" type="checkbox" /> High-pass</label>
									<template v-if="workChain.highpass.on"><input v-model.number="workChain.highpass.cutoff_hz" type="number" min="1" step="10" title="cutoff Hz" /><input v-model.number="workChain.highpass.order" type="number" min="1" max="10" title="order" /></template></div>
								<div class="filt-row"><label class="chk"><input v-model="workChain.lowpass.on" type="checkbox" /> Low-pass</label>
									<template v-if="workChain.lowpass.on"><input v-model.number="workChain.lowpass.cutoff_hz" type="number" min="1" step="100" title="cutoff Hz" /><input v-model.number="workChain.lowpass.order" type="number" min="1" max="10" title="order" /></template></div>
								<div class="filt-row"><label class="chk"><input v-model="workChain.notch.on" type="checkbox" /> Notch ×harmonics</label>
									<template v-if="workChain.notch.on"><input v-model.number="workChain.notch.q" type="number" min="1" step="5" title="Q" /></template></div>
								<div v-if="workChain.notch.on" class="filt-harm">
									<label v-for="h in [1,2,3,4,5]" :key="'h'+h" class="chk">
										<input type="checkbox" :checked="workChain.notch.harmonics.includes(h)"
											@change="workChain.notch.harmonics = ($event.target as HTMLInputElement).checked ? [...workChain.notch.harmonics, h].sort() : workChain.notch.harmonics.filter((x)=>x!==h)" /> {{ h }}×
									</label>
								</div>

								<div v-if="filterBusy" class="setting-note"><v-progress-circular indeterminate x-small /> previewing…</div>
								<div v-if="filterErr" class="render-msg">{{ filterErr }}</div>
								<div v-if="filterSkipped.length" class="setting-note">Preview-only note: {{ filterSkipped.join('; ') }} — bake applies at full rate.</div>

								<div class="filt-actions">
									<select class="prof-sel" @change="applyProfile(($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).value=''">
										<option value="">Load profile…</option>
										<option v-for="p in profiles" :key="p.id" :value="p.id">{{ p.name }}</option>
									</select>
									<button class="linkbtn" @click="saveProfile">Save…</button>
								</div>
								<div class="filt-actions">
									<button class="applybtn" :disabled="baking || !chainActive(workChain)" @click="applyFilter"
										title="Keep this filtered version as the op's default. Lite recomputes it live; Full & FRM PNG stay raw until you Bake."><v-icon name="done" x-small /> Apply (Lite)</button>
									<button class="processbtn" :disabled="baking || !chainActive(workChain)" @click="bakeFilters"
										title="Reprocess the op on the host so ALL outputs (Lite, Full, FRM PNG) are filtered. Heavier; needs the orchestrator; admin-only."><v-icon :name="baking ? 'hourglass_top' : 'save'" x-small /> {{ baking ? 'Baking…' : 'Bake all' }}</button>
									<button v-if="savedChain" class="recrawlbtn" :disabled="baking" @click="clearFilter">Clear</button>
								</div>
							</template>
						</template>
					</div>
				</div>

				<div v-if="!stacked && !detailHidden" class="resizer" @pointerdown="startColBResize" title="Drag to resize"></div>

				<!-- COL 3+4: signals + FRM — independently hideable, resizable against each other -->
				<div ref="rightAreaEl" class="right-area">
					<div v-if="!stacked && (colStackHidden || detailHidden)" class="fold-restore">
						<button v-if="colStackHidden" class="expandbtn" title="Show the samples/operations column" @click="colStackHidden = false">
							<v-icon name="chevron_right" x-small /> Lists
						</button>
						<button v-if="detailHidden" class="expandbtn" title="Show the sample/operation detail column" @click="detailHidden = false">
							<v-icon name="chevron_right" x-small /> Detail
						</button>
					</div>

					<div class="right-row" :class="{ stacked }">
						<div v-if="showForce" class="card col-charts"
							:style="(!stacked && showFRM) ? { flexBasis: (rightSplit * 100) + '%' } : {}">
							<div class="graphs-head">
								<span class="graphs-title"><v-icon name="insights" small /> Signals<span v-if="liveOn" class="live-badge">LIVE · drag to crop</span></span>
								<div class="toggle">
									<button class="tbtn icobtn" :class="{ on: rectZoomTool }" title="Rectangular zoom — drag a box on any graph"
										:style="rectZoomTool ? { background: '#0ea5e9', borderColor: '#0ea5e9' } : {}"
										@click="rectZoomTool = !rectZoomTool"><v-icon name="crop_free" x-small /></button>
									<button class="tbtn icobtn" title="Reset zoom" :disabled="!zoomed" @click="resetZoom"><v-icon name="restart_alt" x-small /></button>
									<button v-if="effectiveMode === 'force'" class="tbtn rpmbtn" :class="{ on: showRpm }"
										:style="showRpm ? { background: '#a855f7', borderColor: '#a855f7' } : {}"
										@click="showRpm = !showRpm">RPM</button>
									<button class="tbtn" :class="{ on: chartMode === 'force' }"
										:style="chartMode === 'force' ? { background: '#334155', borderColor: '#334155' } : {}"
										@click="chartMode = 'force'">Force</button>
									<button class="tbtn" :class="{ on: chartMode === 'fft' }"
										:style="chartMode === 'fft' ? { background: '#334155', borderColor: '#334155' } : {}"
										@click="chartMode = 'fft'">FFT</button>
								</div>
							</div>
							<div v-if="!detail" class="empty">Select an operation to view its signals</div>
							<div v-else class="charts-col">
								<ForceChart v-for="c in charts" :key="c.key" v-bind="c" :hover-index="hoverIndex" @hover="hoverIndex = $event"
									:crop-editable="liveOn && c.kind === 'env'" :active="c.key === axis"
									:overlay="(chartMode === 'fft' && filtersOpen && c.kind === 'line' && c.key === axis) ? filterFftOverlay : null"
									:view-start="zoomStart" :view-end="zoomEnd" :zoom-tool="rectZoomTool" @zoom="onChartZoom"
									@update:crop-start="cropStartSec = $event" @update:crop-end="cropEndSec = $event" />
							</div>
						</div>

						<div v-if="!stacked && showForce && showFRM" class="resizer" @pointerdown="startSplitResize" title="Drag to resize"></div>

						<div v-if="showFRM" class="card col-frm frm-col"
							:style="(!stacked && showForce) ? { flexBasis: ((1 - rightSplit) * 100) + '%' } : {}">
							<div class="frm-head">
								<span class="frm-kicker"><v-icon name="fingerprint" small /> {{ octreeOn ? (gridActive ? 'Full FRM · gridded' : 'Full FRM') : (liveOn ? 'Lite FRM' : 'FRM figure') }}</span>
								<span v-if="(octreeOn || liveOn) && fullResPoints" class="frm-res"
									:title="`Displayed ${displayedPoints.toLocaleString()} of ${fullResPoints.toLocaleString()} full-resolution points`">
									<v-icon name="grain" x-small /> {{ fmtPts(displayedPoints) }} / {{ fmtPts(fullResPoints) }}<template v-if="resolutionPct != null"> · {{ resolutionPct }}%</template>
								</span>
								<span v-if="gridActive && gridFidelityPct != null" class="frm-fid" :class="{ good: gridFidelityPct >= 95 }"
									:title="`Interpolated-grid fidelity (hold-out-arms CV). Arm/cell ratio ${detail.grid_arm_ratio?.toFixed?.(1) ?? '—'}`">
									grid · fidelity ~{{ gridFidelityPct }}%
								</span>
								<span v-else-if="gridActive" class="frm-fid" title="Fidelity could not be computed (too few arms)">grid · fidelity n/a</span>
								<span v-if="bakedChain" class="frm-fid good" :title="`Baked filters: ${chainSummary(bakedChain)}`">⚙ filtered</span>
								<span v-else-if="compareOn" class="frm-fid" :title="chainSummary(workChain)">compare · preview</span>
								<span v-else-if="filteredSoloOn" class="frm-fid" :title="`Lite live-filtered: ${chainSummary(savedChain)} — Full & FRM PNG still raw until baked`">filtered · Lite</span>
								<div class="toggle">
									<div class="segmode">
										<button class="segbtn" :class="{ on: frmMode==='figure' }" @click="frmMode='figure'" title="Prerendered figure (instant)">Figure</button>
										<button class="segbtn" :class="{ on: frmMode==='lite' }" :disabled="!liveAvailable" @click="liveAvailable && (frmMode='lite')" :title="liveAvailable ? 'Lite interactive cloud (reacts to crop/feed)' : 'No live cache — reprocess to enable'">Lite</button>
										<button class="segbtn" :class="{ on: frmMode==='full' }" :disabled="buildingOctree" @click="octreeAvailable ? (frmMode='full') : buildOctree()" :title="octreeAvailable ? 'Full-resolution octree (LOD-streamed)' : 'Build the full-resolution octree on the host'"><v-icon v-if="buildingOctree" name="hourglass_top" x-small /> Full</button>
									</div>
									<button v-if="frmMode==='full'" class="tbtn" :class="{ on: gridFull }" :disabled="buildingOctree"
										:title="gridAvailable ? 'Interpolated-grid octree (filled surface)' : 'Build the interpolated grid on the host'"
										:style="gridFull ? { background: '#0891b2', borderColor: '#0891b2' } : {}"
										@click="gridFull = !gridFull"><v-icon name="grid_on" x-small /> Gridded</button>
									<select v-if="octreeOn || liveOn" v-model="zSeries" class="zsel" title="Drive the Z axis from a force series (3D view — drag to rotate)">
										<option value="none">2D</option>
										<option value="Fx">Z = Fx</option>
										<option value="Fy">Z = Fy</option>
										<option value="Fz">Z = Fz</option>
									</select>
									<input v-if="(octreeOn || liveOn) && zSeries !== 'none'" type="range" class="zslider"
										min="0" max="2" step="0.05" v-model.number="zScale"
										title="Z exaggeration (or a 3-finger vertical swipe on the plot)" />
									<button v-if="detail && (liveOn || octreeOn || detail[`frm_${axis.toLowerCase()}`])" class="tbtn"
										:title="(liveOn || octreeOn) ? 'Download the current view (this zoom) as a PNG' : 'Download this FRM image'"
										@click="downloadFrm"><v-icon name="download" x-small /></button>
									<button v-for="a in AXES" :key="a" class="tbtn" :class="{ on: axis === a }"
										:style="axis === a ? { background: AXIS_COLOR[a], borderColor: AXIS_COLOR[a] } : {}"
										@click="setAxis(a)">{{ a }}</button>
								</div>
							</div>
							<div class="frm-img">
								<div v-if="!detail" class="empty">Select an operation</div>
								<FrmOctree v-else-if="octreeOn" ref="frmOctreeRef"
									:octree-path="gridActive ? detail.grid_octree_path : detail.octree_path" :axis="axis"
									:colormap="colormap" :point-size="pointSize" :cmin="cmin" :cmax="cmax"
									:z-series="zSeries" :z-scale="zScale"
									:total-points="gridActive ? Number(detail.grid_octree_points) : fullResPoints"
									:fill="gridActive" :cell-size="Number(detail.grid_cell_mm) || 1"
									:min-node-px="octreeMinNodePx" :budget-cap="octreeBudgetCap"
									@climits="onClimits" @points="displayedPoints = $event" @zscale="zScale = $event" />
								<!-- Compare mode: raw | filtered, sharing one view (linked pan/zoom) + colour scale. -->
								<div v-else-if="compareOn" class="frm-compare" :class="{ stacked }">
									<FrmCloud ref="frmCloudRef" :cache-file-id="detail.live_cache_file" :cache-override="rawDecimatedCache"
										:axis="axis" :feed="editFeed" :diam="editDiam" :inner-diam="editInnerDiam" :speed-mode="speedMode"
										:rpm="editRpm" :vc="editVc" :time-scale="timeScale" :ppr="editPpr"
										:crop-start-sec="cropStartSec" :crop-end-sec="cropEndSec"
										:stride="plotStride" :gridding="gridding" :grid-n="gridN"
										:point-size="pointSize" :colormap="colormap" :cmin="cmin" :cmax="cmax"
										:shared-view="compareView" pane-label="raw"
										@loaded="onCloudLoaded" @climits="onClimits" @points="displayedPoints = $event" />
									<FrmCloud :cache-override="filteredCache" :cache-file-id="detail.live_cache_file"
										:axis="axis" :feed="editFeed" :diam="editDiam" :inner-diam="editInnerDiam" :speed-mode="speedMode"
										:rpm="editRpm" :vc="editVc" :time-scale="timeScale" :ppr="editPpr"
										:crop-start-sec="cropStartSec" :crop-end-sec="cropEndSec"
										:stride="plotStride" :gridding="gridding" :grid-n="gridN"
										:point-size="pointSize" :colormap="colormap"
										:cmin="cmin" :cmax="cmax"
										:shared-view="compareView" pane-label="filtered" />
								</div>
								<FrmCloud v-else-if="filteredSoloOn" ref="frmCloudRef" :cache-override="filteredCache" :cache-file-id="detail.live_cache_file"
										:axis="axis" :feed="editFeed" :diam="editDiam" :inner-diam="editInnerDiam" :speed-mode="speedMode"
										:rpm="editRpm" :vc="editVc" :time-scale="timeScale" :ppr="editPpr"
										:crop-start-sec="cropStartSec" :crop-end-sec="cropEndSec"
										:stride="plotStride" :gridding="gridding" :grid-n="gridN"
										:point-size="pointSize" :colormap="colormap" :cmin="cmin" :cmax="cmax"
										:z-series="zSeries" :z-scale="zScale"
										@loaded="onCloudLoaded" @climits="onClimits" @points="displayedPoints = $event"
										@zscale="zScale = $event" />
									<FrmCloud v-else-if="liveOn" ref="frmCloudRef" :cache-file-id="detail.live_cache_file"
									:axis="axis" :feed="editFeed" :diam="editDiam" :inner-diam="editInnerDiam" :speed-mode="speedMode"
									:rpm="editRpm" :vc="editVc" :time-scale="timeScale" :ppr="editPpr"
									:crop-start-sec="cropStartSec" :crop-end-sec="cropEndSec"
									:stride="plotStride" :gridding="gridding" :grid-n="gridN"
									:point-size="pointSize" :colormap="colormap" :cmin="cmin" :cmax="cmax"
									:z-series="zSeries" :z-scale="zScale"
									@loaded="onCloudLoaded" @climits="onClimits" @points="displayedPoints = $event"
									@zscale="zScale = $event" />
								<div v-else-if="frmLoading" class="loading"><v-progress-circular indeterminate /></div>
								<img v-else-if="frmUrl" :src="frmUrl" :alt="`FRM ${axis}`" />
								<div v-else class="empty">No {{ axis }} fingerprint</div>
								<div v-if="octreeMsg && !liveOn" class="render-msg frm-render-msg">{{ octreeMsg }}</div>
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>
	</private-view>
</template>

<style scoped>
.fd {
	padding: 20px 24px 40px;
	font-family: var(--theme--fonts--sans--font-family, -apple-system, 'Segoe UI', Roboto, sans-serif);
	color: var(--theme--foreground, #1e293b);
	container-type: inline-size;   /* size children to the real content width, not the viewport */
}
/* Thin horizontal banner: title + counts on the left, panel toggles on the right. */
.hero { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; padding: 6px 14px; border-radius: 12px;
	color: #fff; background: linear-gradient(120deg, var(--theme--primary, #1d4ed8), #0d9488);
	box-shadow: 0 8px 20px -12px rgba(29, 78, 216, 0.5); flex-wrap: wrap; }
.hero-badge { display: inline-flex; align-items: center; gap: 7px; font-weight: 750; font-size: 14px; }
.hero-badge :deep(.v-icon) { --v-icon-color: #fff; }
.hero-stat { font-size: 12px; font-weight: 600; opacity: 0.9; }
.hero-spacer { flex: 1 1 auto; }
.hero .pt-label { color: rgba(255, 255, 255, 0.8); }
.hero .pt-chip { color: #fff; background: rgba(255, 255, 255, 0.16); border-color: rgba(255, 255, 255, 0.28); }
.hero .pt-chip.on { color: var(--theme--primary, #1d4ed8); background: #fff; border-color: #fff; }
.hero .pt-chip:disabled { opacity: 0.5; }

.loading { display: grid; place-items: center; padding: 40px; }
.loading.sm { padding: 18px; }

.layout {
	display: grid;
	gap: 0; align-items: stretch;
	overflow: hidden;   /* the measured height is exact; panels scroll internally, the page doesn't */
}
.layout.stacked { align-items: start; overflow: visible; }
.layout.dragging { cursor: col-resize; }
.layout.dragging * { user-select: none; }

.col-stack, .col-charts, .col-frm, .right-area { min-width: 0; min-height: 0; }
.col-stack { display: flex; flex-direction: column; gap: 14px; padding-right: 6px; }
.panel-samples { flex: 0 0 auto; }
.panel-ops { flex: 1 1 auto; min-height: 0; }
.panel-ops .list { max-height: none; flex: 1 1 auto; }
/* Detail column = header-sized cards by default; the ONE open accordion (op detail / stats
   / filters, mutually exclusive) takes the remaining height and scrolls. A collapsed card
   must shrink to just its header — otherwise it kept flex:1 and left a big empty box. */
.col-stack .info { flex: 0 0 auto; min-height: 0; }
.col-stack .info-op, .col-stack .info-display, .col-stack .info-stats, .col-stack .info-filters { overflow-y: auto; }
.col-stack .info-op:not(.collapsed),
.col-stack .info-display:not(.collapsed),
.col-stack .info-stats:not(.collapsed),
.col-stack .info-filters:not(.collapsed) { flex: 1 1 auto; }
.col-stack .info.collapsed { flex: 0 0 auto; overflow: visible; }
.layout.stacked .col-stack .info:last-child { overflow: visible; }
.layout.stacked .panel-ops .list { max-height: 40vh; flex: none; }
.layout.stacked .col-charts .chart { flex: none; min-height: 180px; }
.col-charts { display: flex; flex-direction: column; }
.col-charts .charts-col { flex: 1 1 auto; min-height: 0; }
.col-charts .chart { flex: 1 1 0; }

/* Drag handles between columns (grid tracks on desktop, flex items in the
   Signals/FRM row) — thin, with a grab affordance on hover/drag. */
.resizer { width: 6px; cursor: col-resize; position: relative; flex: 0 0 6px; }
.resizer::after {
	content: ''; position: absolute; left: 2px; top: 10%; bottom: 10%; width: 2px;
	border-radius: 2px; background: var(--theme--border-color, #dbe2ea); transition: background 0.15s ease;
}
.resizer:hover::after, .layout.dragging .resizer::after { background: var(--theme--primary, #1d4ed8); }

.panel {
	background: var(--theme--background-subdued, #f7f9fb);
	border: 1px solid var(--theme--border-color-subdued, #e7ebf0);
	border-radius: 16px; display: flex; flex-direction: column; overflow: hidden;
}
.panel-samples .list { max-height: 30vh; }
.panel-ops .list { max-height: 38vh; }
.panel-head {
	display: flex; align-items: center; gap: 8px; padding: 12px 14px;
	font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
	color: var(--theme--foreground-subdued, #6b7684);
	border-bottom: 1px solid var(--theme--border-color-subdued, #e7ebf0);
}
.chip {
	font-size: 10px; font-weight: 700; color: var(--theme--primary, #1d4ed8);
	background: color-mix(in srgb, var(--theme--primary, #1d4ed8) 12%, transparent);
	padding: 1px 7px; border-radius: 99px;
}
.clearbtn { margin-left: auto; border: 0; background: none; cursor: pointer; font: inherit; font-size: 11px; font-weight: 700; text-transform: none; letter-spacing: 0; color: var(--theme--primary, #1d4ed8); }
.search {
	margin: 11px 12px 5px; padding: 8px 11px; font: inherit; font-size: 12.5px;
	border: 1px solid var(--theme--border-color-subdued, #e7ebf0); border-radius: 9px;
	background: var(--theme--background, #fff); color: inherit; outline: none;
}
.search:focus { border-color: var(--theme--primary, #1d4ed8); }
.list { overflow-y: auto; padding: 7px 11px 12px; display: flex; flex-direction: column; gap: 9px; }
/* Data-quality stoplight dot in the row's top-right corner (green ready · blue processing ·
   yellow octree-only · red none). */
.qdot { position: absolute; top: 8px; right: 9px; width: 6px; height: 6px; border-radius: 99px; }
.qdot.green { background: #16a34a; }
.qdot.yellow { background: #f59e0b; }
.qdot.blue { background: #3b82f6; }
.qdot.red { background: #ef4444; }
.rowcard {
	position: relative;
	text-align: left; font: inherit; cursor: pointer; color: inherit;
	background: var(--theme--background, #fff); border: 1px solid var(--theme--border-color-subdued, #e7ebf0);
	border-radius: 12px; padding: 11px 13px; display: flex; flex-direction: column; gap: 4px;
	transition: transform 0.12s ease, box-shadow 0.12s ease, border-color 0.12s ease;
}
.rowcard:hover { transform: translateY(-2px); box-shadow: 0 10px 22px -16px rgba(15, 23, 42, 0.4); }
.rowcard.active { border-color: var(--theme--primary, #1d4ed8); box-shadow: 0 0 0 1px var(--theme--primary, #1d4ed8) inset; }
.mono { font-family: var(--theme--fonts--monospace--font-family, 'SF Mono', Menlo, monospace); font-weight: 700; font-size: 13px; overflow-wrap: break-word; word-break: normal; }
.mono.sm { font-size: 11.5px; }
.sub { font-size: 11px; color: var(--theme--foreground-subdued, #6b7684); }
.pill, .badge { align-self: flex-start; margin-top: 2px; font-size: 10px; font-weight: 700; padding: 1px 8px; border-radius: 99px; }
.pill { color: var(--theme--primary, #1d4ed8); background: color-mix(in srgb, var(--theme--primary, #1d4ed8) 12%, transparent); }
.badge { color: #fff; }
.empty { padding: 20px 16px; text-align: center; color: var(--theme--foreground-subdued, #98a2b3); font-size: 12.5px; }
.empty.sm { padding: 14px; font-size: 12px; }

.card {
	background: var(--theme--background, #fff); border: 1px solid var(--theme--border-color-subdued, #e7ebf0);
	border-radius: 16px; padding: 16px 18px;
}
.info-head {
	display: flex; align-items: center; justify-content: space-between; gap: 8px;
	font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
	color: var(--theme--foreground-subdued, #6b7684); margin-bottom: 11px;
}
.openbtn {
	display: inline-flex; align-items: center; gap: 3px; border: 0; cursor: pointer; font: inherit;
	font-size: 10.5px; font-weight: 700; text-transform: none; letter-spacing: 0;
	color: var(--theme--primary, #1d4ed8); background: color-mix(in srgb, var(--theme--primary, #1d4ed8) 10%, transparent);
	padding: 3px 8px; border-radius: 8px;
}
.openbtn:hover { background: color-mix(in srgb, var(--theme--primary, #1d4ed8) 18%, transparent); }
.info-code { font-size: 13px; margin-bottom: 12px; }
.kv { display: grid; grid-template-columns: auto 1fr; gap: 7px 12px; font-size: 12.5px; margin-bottom: 4px; }
.kv span:nth-child(odd) { color: var(--theme--foreground-subdued, #6b7684); white-space: nowrap; }
.kv span:nth-child(even) { font-weight: 600; text-align: right; }
.stat-sep {
	margin: 12px 0 9px; font-size: 9.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
	color: var(--theme--foreground-subdued, #98a2b3); border-top: 1px solid var(--theme--border-color-subdued, #eef1f5); padding-top: 10px;
}
.statgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; }
.stat {
	background: var(--theme--background-subdued, #f7f9fb); border: 1px solid var(--theme--border-color-subdued, #e7ebf0);
	border-radius: 8px; padding: 5px 9px; display: flex; flex-direction: column; gap: 0;
}
.s-top { display: flex; align-items: baseline; gap: 4px; flex-wrap: wrap; }
.s-val { font-size: 13px; font-weight: 750; letter-spacing: -0.01em; font-variant-numeric: tabular-nums; line-height: 1.15; }
.s-unit { font-size: 9.5px; font-weight: 600; color: var(--theme--foreground-subdued, #94a3b8); letter-spacing: 0.02em; }
.s-lab { font-size: 8.5px; text-transform: uppercase; letter-spacing: 0.03em; color: var(--theme--foreground-subdued, #6b7684); font-weight: 600; margin-top: 1px; }
/* editable cut-param boxes: an input styled like the value, with a dashed underline so it
   reads as editable WITHOUT clicking; the unit sits inline to its right (like the read-only
   boxes) to save vertical space. Modified = accent ring. */
.stat.edit { background: var(--theme--background, #fff); transition: border-color 0.12s, box-shadow 0.12s; }
.stat .s-inp {
	width: 4.4em; max-width: 100%; font: inherit; font-size: 13px; font-weight: 750; font-variant-numeric: tabular-nums;
	background: transparent; color: inherit; padding: 0 0 1px; line-height: 1.15;
	border: 0; border-bottom: 1px dashed var(--theme--border-color, #c7d0da); border-radius: 0;
}
.stat .s-inp::-webkit-outer-spin-button, .stat .s-inp::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.stat .s-inp { -moz-appearance: textfield; appearance: textfield; }
.stat .s-inp:hover { border-bottom-color: var(--theme--foreground-subdued, #94a3b8); }
.stat .s-inp:focus { outline: none; border-bottom: 1px solid var(--theme--primary, #1d4ed8); }
.stat.modified { border-color: var(--theme--primary, #1d4ed8); box-shadow: inset 0 0 0 1px var(--theme--primary, #1d4ed8); }
.stat.modified .s-lab { color: var(--theme--primary, #1d4ed8); }

/* Right area: Signals + FRM, independently hideable/resizable against each other. */
.right-area { display: flex; flex-direction: column; gap: 10px; }
.panel-toggles { display: flex; align-items: center; gap: 8px; padding: 0 2px; }
.pt-label { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--theme--foreground-subdued, #98a2b3); margin-right: 2px; }
.pt-chip {
	display: inline-flex; align-items: center; gap: 5px; font: inherit; font-size: 11.5px; font-weight: 650;
	cursor: pointer; padding: 5px 12px; border-radius: 99px; color: var(--theme--foreground-subdued, #6b7684);
	background: var(--theme--background-subdued, #f1f5f9); border: 1px solid var(--theme--border-color-subdued, #e7ebf0);
	transition: all 0.12s ease;
}
.pt-chip.on { color: var(--theme--primary, #1d4ed8); background: color-mix(in srgb, var(--theme--primary, #1d4ed8) 10%, transparent); border-color: color-mix(in srgb, var(--theme--primary, #1d4ed8) 30%, transparent); }
.pt-chip:disabled { opacity: 0.55; cursor: not-allowed; }
.right-row { display: flex; gap: 0; flex: 1 1 auto; min-height: 0; align-items: stretch; }
.right-row.stacked { flex-direction: column; }
.right-row > .card { flex: 1 1 auto; min-width: 0; overflow: hidden; }

.graphs-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 13px; flex-wrap: wrap; gap: 6px; }
.graphs-title, .frm-kicker {
	display: inline-flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 700;
	text-transform: uppercase; letter-spacing: 0.05em; color: var(--theme--foreground-subdued, #6b7684);
}
.toggle { display: flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end; }
.tbtn {
	font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; padding: 5px 13px; border-radius: 9px;
	color: var(--theme--foreground-subdued, #6b7684); background: var(--theme--background-subdued, #f1f5f9);
	border: 1px solid var(--theme--border-color-subdued, #e7ebf0); transition: all 0.12s ease;
}
.tbtn.on { color: #fff; }
.tbtn.icobtn { padding: 5px 9px; display: inline-flex; align-items: center; }
.charts-col { display: flex; flex-direction: column; gap: 13px; }

.col-frm { display: flex; flex-direction: column; gap: 11px; min-height: 0; }
.frm-head { flex: 0 0 auto; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 6px; }
.frm-res { display: inline-flex; align-items: center; gap: 3px; font-size: 10.5px; font-weight: 600; font-variant-numeric: tabular-nums;
	color: var(--theme--foreground-subdued, #6b7684); background: var(--theme--background-subdued, #f1f5f9);
	border: 1px solid var(--theme--border-color-subdued, #e7ebf0); border-radius: 99px; padding: 1px 8px; margin-right: auto; }
.frm-fid { font-size: 10px; padding: 1px 7px; border-radius: 99px; font-weight: 700;
	color: #b45309; background: color-mix(in srgb, #d97706 14%, transparent); white-space: nowrap; }
.frm-fid.good { color: #15803d; background: color-mix(in srgb, #16a34a 14%, transparent); }
.segmode { display: inline-flex; border-radius: 8px; overflow: hidden; border: 1px solid var(--theme--border-color-subdued, #d7dee6); }
.segbtn { font: inherit; font-size: 11px; font-weight: 700; cursor: pointer; border: 0; padding: 5px 11px; background: var(--theme--background, #fff); color: var(--theme--foreground-subdued, #64748b); border-right: 1px solid var(--theme--border-color-subdued, #e7ebf0); }
.segbtn:last-child { border-right: 0; }
.segbtn.on { background: #0891b2; color: #fff; }
.segbtn:disabled { opacity: 0.4; cursor: default; }
.zslider { width: 70px; accent-color: #0891b2; vertical-align: middle; cursor: pointer; }
.stats-table { width: 100%; border-collapse: collapse; font-size: 11.5px; margin: 6px 0 4px; }
.stats-table th { text-align: right; font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--theme--foreground-subdued, #6b7684); padding: 2px 6px; }
.stats-table td { text-align: right; padding: 3px 6px; font-variant-numeric: tabular-nums; border-top: 1px solid var(--theme--border-color-subdued, #eef1f5); }
.stats-table td:first-child { text-align: left; color: var(--theme--foreground-subdued, #6b7684); font-weight: 600; white-space: nowrap; }
.stat-bad { color: #dc2626; font-weight: 700; }
.stats-win { font-size: 10.5px; color: var(--theme--foreground-subdued, #98a2b3); }
.stats-rpm { margin-top: 2px; }
.stats-compute { margin-top: 4px; }
.acc-head {
	display: flex; align-items: center; gap: 4px; width: 100%; text-align: left;
	background: none; border: 0; cursor: pointer; font: inherit;
	font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
	color: var(--theme--foreground-subdued, #98a2b3); margin: 6px 0 4px; padding: 6px 0 0;
	border-top: 1px solid var(--theme--border-color-subdued, #eef1f5);
}
.acc-head:hover { color: var(--theme--foreground, #1e293b); }
.filt-row { display: flex; align-items: center; gap: 6px; margin: 3px 0; }
.filt-row .chk { flex: 1 1 auto; }
.filt-row input, .filt-row select { width: 60px; font: inherit; font-size: 12px; padding: 3px 6px; border-radius: 7px; border: 1px solid var(--theme--border-color-subdued, #e7ebf0); background: var(--theme--background, #fff); color: inherit; }
.filt-row select { width: auto; }
.filt-harm { display: flex; gap: 8px; margin: 2px 0 6px 20px; }
.filt-harm .chk { font-size: 11.5px; }
.filt-actions { display: flex; gap: 8px; align-items: center; margin-top: 8px; }
.prof-sel { flex: 1 1 auto; font: inherit; font-size: 12px; padding: 5px 8px; border-radius: 8px; border: 1px solid var(--theme--border-color-subdued, #e7ebf0); background: var(--theme--background, #fff); color: inherit; }
/* compare: two square viewports sharing the FRM area (side-by-side; stacked on mobile) */
.frm-compare { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; width: 100%; height: 100%; min-height: 0; }
.frm-compare.stacked { grid-template-columns: 1fr; grid-template-rows: 1fr 1fr; }
.frm-compare > * { min-width: 0; min-height: 0; }
.zsel { font: inherit; font-size: 11px; font-weight: 650; padding: 3px 7px; border-radius: 8px; cursor: pointer;
	border: 1px solid var(--theme--border-color, #d1d9e6); background: var(--theme--background, #fff); color: var(--theme--foreground, #334155); }
.frm-img { flex: 1 1 auto; display: flex; align-items: center; justify-content: center; min-width: 0; min-height: 220px; overflow: hidden; }
.frm-img img { max-width: 100%; max-height: 100%; width: auto; height: auto; object-fit: contain; border-radius: 8px; border: 1px solid var(--theme--border-color-subdued, #e7ebf0); }
.layout.stacked .frm-img { aspect-ratio: 1 / 1; min-height: 0; flex: 0 0 auto; }
.frm-img > .frm-cloud, .frm-img > .frm-octree { align-self: stretch; }

.tbtn:disabled { opacity: 0.45; cursor: not-allowed; }

/* Live badge + collapse chevrons */
.live-badge { margin-left: 8px; font-size: 9px; font-weight: 800; letter-spacing: 0.06em; color: #7c3aed;
	background: color-mix(in srgb, #7c3aed 12%, transparent); padding: 2px 7px; border-radius: 99px; }
.collapsebtn, .chevbtn {
	display: inline-flex; align-items: center; justify-content: center; border: 0; cursor: pointer; padding: 1px;
	margin-left: 4px; color: var(--theme--foreground-subdued, #94a3b8); background: transparent; border-radius: 6px;
}
.chevbtn { margin-left: 0; margin-right: 2px; }
.collapsebtn:hover, .chevbtn:hover { background: var(--theme--background-subdued, #eef2f7); color: var(--theme--foreground, #1e293b); }
.expandbtn {
	display: inline-flex; align-items: center; gap: 3px; align-self: flex-start; font: inherit; font-size: 11px; font-weight: 700;
	cursor: pointer; padding: 5px 10px; border-radius: 9px; margin-bottom: 2px;
	color: var(--theme--primary, #1d4ed8); background: color-mix(in srgb, var(--theme--primary, #1d4ed8) 10%, transparent);
	border: 1px solid color-mix(in srgb, var(--theme--primary, #1d4ed8) 22%, transparent);
}
.fold-restore { display: flex; gap: 6px; flex: 0 0 auto; }
.ih-actions { display: inline-flex; align-items: center; gap: 4px; }
.card.info.collapsed { padding-bottom: 12px; }
.card.info.collapsed .info-head { margin-bottom: 0; }

/* Live-mode editable metadata + plotting settings */
.linkbtn { border: 0; background: transparent; cursor: pointer; font: inherit; font-size: 10px; font-weight: 700;
	color: var(--theme--primary, #1d4ed8); text-transform: none; letter-spacing: 0; float: right; padding: 0; }
.edit-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; }
.edit-grid label { display: flex; flex-direction: column; gap: 3px; font-size: 10.5px; font-weight: 700;
	text-transform: uppercase; letter-spacing: 0.03em; color: var(--theme--foreground-subdued, #6b7684); }
.edit-grid label.wide { grid-column: 1 / -1; }
.edit-grid label.chk { flex-direction: row; align-items: center; gap: 6px; text-transform: none; letter-spacing: 0; font-size: 12px; }
.edit-grid .u { font-weight: 500; color: var(--theme--foreground-subdued, #a4adba); text-transform: none; }
.edit-grid input[type="number"], .edit-grid select, .render-row input {
	font: inherit; font-size: 13px; font-weight: 600; text-transform: none; letter-spacing: 0; padding: 5px 8px;
	border: 1px solid var(--theme--border-color, #d1d9e6); border-radius: 8px; background: var(--theme--background, #fff);
	color: var(--theme--foreground, #1e293b); width: 100%; box-sizing: border-box;
}
.edit-grid input:disabled { opacity: 0.5; cursor: not-allowed; }
.speed-row { display: flex; gap: 6px; }
.speed-row select { flex: 1 1 auto; } .speed-row input { flex: 0 0 82px; }
.render-row { display: flex; align-items: flex-end; gap: 8px; }
.render-row label { display: flex; flex-direction: column; gap: 3px; font-size: 10.5px; font-weight: 700;
	text-transform: uppercase; letter-spacing: 0.03em; color: var(--theme--foreground-subdued, #6b7684); flex: 1 1 auto; }
.processbtn {
	display: inline-flex; align-items: center; gap: 5px; font: inherit; font-size: 12px; font-weight: 750; cursor: pointer;
	padding: 7px 14px; border-radius: 9px; color: #fff; background: #7c3aed; border: 0; white-space: nowrap;
}
.processbtn:disabled { opacity: 0.6; cursor: progress; }
.applybtn {
	display: inline-flex; align-items: center; gap: 5px; font: inherit; font-size: 12px; font-weight: 750; cursor: pointer;
	padding: 7px 14px; border-radius: 9px; color: #6d28d9; background: transparent; border: 1.5px solid #7c3aed; white-space: nowrap;
}
.applybtn:disabled { opacity: 0.5; cursor: not-allowed; }
.render-msg { margin-top: 7px; font-size: 11px; color: var(--theme--foreground-subdued, #6b7684); font-style: italic; }
</style>
