<script setup lang="ts">
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue';
import { useApi, useStores } from '@directus/extensions-sdk';
import { useRoute, useRouter } from 'vue-router';
import ForceChart from './ForceChart.vue';
import FrmCloud from './FrmCloud.vue';
import FrmOctree from './FrmOctree.vue';
import type { SpeedMode } from './liveCloud';

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
const liveMode = ref(false);
// Editable geometry (seeded from the cache on load; user edits drive the cloud).
const cropStartSec = ref(0);
const cropEndSec = ref(0);
const editFeed = ref(0.1);
const editDiam = ref(80);
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
const renderPoints = ref(3000000);   // full-res cut-window cache (host caps ~3M)
const rendering = ref(false);
const renderMsg = ref<string | null>(null);
// ---- Full-resolution octree (Phase 2) ----------------------------------------------
// For ops too large for the client cache, the host builds a Potree octree from the raw
// .mat; the browser LOD-streams it (FrmOctree). octreeMode swaps the FRM column to it.
const octreeMode = ref(false);
const buildingOctree = ref(false);
const octreeMsg = ref<string | null>(null);
const octreeAvailable = computed(() => detail.value?.octree_status === 'done' && !!detail.value?.octree_path);
const octreeOn = computed(() => octreeMode.value && octreeAvailable.value);
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
				octreeMsg.value = null; octreeMode.value = true; return;
			}
			if (row?.octree_status === 'error') { octreeMsg.value = `Build failed: ${row.octree_error || 'unknown'}`; return; }
		}
		octreeMsg.value = 'Still building — check back shortly (is the force orchestrator running?).';
	} catch (e: any) {
		octreeMsg.value = e?.response?.status === 403 ? 'Not permitted (admin only) to request a host build.' : (e?.message || 'octree request failed');
	} finally { buildingOctree.value = false; }
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
		if (typeof v.liveMode === 'boolean') liveMode.value = v.liveMode;
	} catch { /* ignore malformed/absent saved layout */ }
})();
watch([colA, colB, rightSplit, showForce, showFRM, colStackHidden, detailHidden, liveMode], () => {
	localStorage.setItem(LAYOUT_KEY, JSON.stringify({
		colA: colA.value, colB: colB.value, rightSplit: rightSplit.value,
		showForce: showForce.value, showFRM: showFRM.value,
		colStackHidden: colStackHidden.value, detailHidden: detailHidden.value,
		// Persist Live so returning to the dashboard keeps the interactive FRM cloud
		// instead of silently dropping back to the static PNG. (liveOn still requires a
		// live cache on the selected op, so ops without one safely show the PNG.)
		liveMode: liveMode.value,
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
	try {
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
					'id', 'peak_fx', 'peak_fy', 'peak_fz',
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
					'directus_files_id.filesize', 'live_cache_file', 'live_render_points', 'pulses_per_rev',
					'octree_status', 'octree_path', 'octree_points'],
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

const stats = computed(() => {
	const d = detail.value;
	if (!d) return [];
	const mrpm = d.mean_rpm != null ? Number(d.mean_rpm).toFixed(0) : '—';
	return [
		// Cutting parameters lead (speed, feed, DoC), matching how the operation was set up.
		{ label: 'Surface speed', value: fmt(d.surface_speed), unit: 'm/min' },
		{ label: 'Feed', value: fmt(d.feed), unit: 'mm/rev' },
		{ label: 'Depth of cut', value: fmt(d.depth_of_cut), unit: 'mm' },
		{ label: 'Diameter', value: fmt(d.cut_diameter), unit: 'mm' },
		{ label: 'Mean RPM', value: mrpm, unit: '' },
		{ label: 'Cut time', value: fmtCutTime(d), unit: '' },
		{ label: 'Dyno gain', value: fmt(d.dyno_gain), unit: 'N/V' },
		{ label: 'Sample rate', value: d.sample_rate ? `${(d.sample_rate / 1000).toFixed(1)}` : '—', unit: 'kHz' },
		{ label: 'File size', value: fmtBytes(d.directus_files_id?.filesize), unit: '' },
	];
});

const showRpm = ref(false);

// Entering Live collapses the sample detail + the op's date/coolant rows to free
// vertical space for the crop plots, cloud, and plotting-settings panel.
watch(liveMode, (on) => { sampleDetailOpen.value = !on; if (on) chartMode.value = 'force'; });
// Live needs a loaded cache; if this op has none, fall back to the static view.
const liveAvailable = computed(() => !!detail.value?.live_cache_file);
const liveOn = computed(() => liveMode.value && liveAvailable.value);

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
	editRpm.value = meta.rpm;
	editRate.value = meta.Fs;
	cacheFs = meta.Fs;
	speedMode.value = 'measured';
	// derive a sensible Vc default from the measured mean speed + diameter
	editVc.value = Math.round(Math.PI * meta.diam * meta.rpm / 1000) || 100;
}
function resetLive() {
	const d = detail.value;
	if (cropWindow.value) { cropStartSec.value = cropWindow.value.start; cropEndSec.value = cropWindow.value.end; }
	if (d) {
		editFeed.value = Number(d.feed) || editFeed.value;
		editDiam.value = Number(d.cut_diameter) || editDiam.value;
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

// Download the CURRENT viewport as a pixel-identical FRM: send the visible bounds +
// colour settings to the host, which re-renders that crop at full resolution in MATLAB
// (same styling as the prerendered PNGs) and returns a PNG we then download. Mirrors the
// Tier-2 request/poll pattern on the analysis row's render_* fields.
const frmCloudRef = ref<any>(null);
const downloadingView = ref(false);
const downloadViewMsg = ref<string | null>(null);
async function downloadViewport() {
	const d = detail.value;
	if (!d?.id || downloadingView.value) return;
	const bounds = frmCloudRef.value?.currentBounds?.();
	if (!bounds) { downloadViewMsg.value = 'No viewport to render yet.'; return; }
	downloadingView.value = true; downloadViewMsg.value = 'Requesting host render…';
	try {
		await api.patch(`/items/machining_force_analysis/${d.id}`, {
			render_status: 'pending',
			render_bounds: bounds,
			render_axis: axis.value,
			render_colormap: colormap.value,
			render_cmin: cauto.value ? null : cminManual.value,
			render_cmax: cauto.value ? null : cmaxManual.value,
			render_requested_at: new Date().toISOString(),
		});
		downloadViewMsg.value = 'Rendering on the host…';
		const deadline = Date.now() + 5 * 60 * 1000;
		while (Date.now() < deadline) {
			await new Promise((r) => setTimeout(r, 2500));
			const res = await api.get(`/items/machining_force_analysis/${d.id}`, { params: { fields: ['render_status', 'render_file', 'render_error'] } });
			const row = res.data?.data;
			if (row?.render_status === 'done' && row.render_file) { downloadFile(row.render_file); downloadViewMsg.value = null; return; }
			if (row?.render_status === 'error') { downloadViewMsg.value = `Render failed: ${row.render_error || 'unknown'}`; return; }
		}
		downloadViewMsg.value = 'Still rendering — is the host force orchestrator running?';
	} catch (e: any) {
		downloadViewMsg.value = e?.response?.status === 403 ? 'Not permitted (admin only) to request a host render.' : (e?.message || 'render request failed');
	} finally { downloadingView.value = false; }
}
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
								<span class="mono sm">{{ o.operation_id?.pass_code || '—' }}</span>
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

					<div class="card info info-op">
						<div class="info-head">
							<span><v-icon name="build" x-small /> Operation detail</span>
							<button v-if="op?.operation_id" class="openbtn" @click="openOpForm">Open <v-icon name="open_in_new" x-small /></button>
						</div>
						<template v-if="detail">
							<div class="info-code mono">{{ opLabel }}</div>
							<div v-if="compactMeta.length" class="kv">
								<template v-for="m in compactMeta" :key="m[0]"><span>{{ m[0] }}</span><span>{{ m[1] }}</span></template>
							</div>

							<!-- Static: force metrics grid. Live: editable plot metadata + plotting settings. -->
							<template v-if="!liveOn">
								<div class="stat-sep">Force metrics</div>
								<div class="statgrid">
									<div v-for="st in stats" :key="st.label" class="stat">
										<div class="s-top"><span class="s-val">{{ st.value }}</span><span v-if="st.unit" class="s-unit">{{ st.unit }}</span></div>
										<span class="s-lab">{{ st.label }}</span>
									</div>
								</div>
							</template>
							<template v-else>
								<div class="stat-sep">Plot metadata <button class="linkbtn" @click="resetLive">Reset</button></div>
								<div class="edit-grid">
									<label>Feed <span class="u">mm/rev</span><input v-model.number="editFeed" type="number" step="0.01" min="0" /></label>
									<label>Diameter <span class="u">mm</span><input v-model.number="editDiam" type="number" step="1" min="0" /></label>
									<label>Pulses/rev<input v-model.number="editPpr" type="number" step="1" min="1" /></label>
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
									<label>Rate <span class="u">Hz</span><input v-model.number="editRate" type="number" step="100" min="1" /></label>
								</div>

								<div class="stat-sep">Plotting settings</div>
								<div class="edit-grid">
									<label>Show every<select v-model.number="plotStride"><option :value="1">all pts</option><option :value="2">2nd</option><option :value="5">5th</option><option :value="10">10th</option><option :value="25">25th</option></select></label>
									<label>Colour<select v-model="colormap"><option value="viridis">viridis</option><option value="inferno">inferno</option><option value="grayscale">grayscale</option></select></label>
									<label>Point size<input v-model.number="pointSize" type="number" step="0.2" min="0.4" max="6" /></label>
									<label class="chk"><input v-model="gridding" type="checkbox" /> Grid binning</label>
									<label class="chk wide"><input v-model="cauto" type="checkbox" /> Auto colour limits <span class="u">(prctile 1 / 99)</span></label>
									<label>Colour min <span class="u">N</span><input v-model.number="cminManual" type="number" step="1" :disabled="cauto" /></label>
									<label>Colour max <span class="u">N</span><input v-model.number="cmaxManual" type="number" step="1" :disabled="cauto" /></label>
								</div>

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
						<div v-else-if="loadingDetail" class="loading sm"><v-progress-circular indeterminate small /></div>
						<div v-else class="empty sm">Select an operation</div>
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
									<button class="tbtn" :class="{ on: liveMode }" :disabled="!liveAvailable"
										:title="liveAvailable ? 'Interactive live plotting' : 'No live cache — reprocess to enable'"
										:style="liveMode ? { background: '#7c3aed', borderColor: '#7c3aed' } : {}"
										@click="liveMode = !liveMode">Live</button>
								</div>
							</div>
							<div v-if="!detail" class="empty">Select an operation to view its signals</div>
							<div v-else class="charts-col">
								<ForceChart v-for="c in charts" :key="c.key" v-bind="c" :hover-index="hoverIndex" @hover="hoverIndex = $event"
									:crop-editable="liveOn && c.kind === 'env'"
									:view-start="zoomStart" :view-end="zoomEnd" :zoom-tool="rectZoomTool" @zoom="onChartZoom"
									@update:crop-start="cropStartSec = $event" @update:crop-end="cropEndSec = $event" />
							</div>
						</div>

						<div v-if="!stacked && showForce && showFRM" class="resizer" @pointerdown="startSplitResize" title="Drag to resize"></div>

						<div v-if="showFRM" class="card col-frm frm-col"
							:style="(!stacked && showForce) ? { flexBasis: ((1 - rightSplit) * 100) + '%' } : {}">
							<div class="frm-head">
								<span class="frm-kicker"><v-icon name="fingerprint" small /> {{ octreeOn ? 'Full-res FRM' : (liveOn ? 'Live FRM' : 'FRM plot') }}</span>
								<div class="toggle">
									<button v-if="liveOn && !octreeOn" class="tbtn" :disabled="downloadingView"
										title="Download this viewport as a full-resolution FRM (host render, pixel-identical to the report PNGs)"
										@click="downloadViewport"><v-icon :name="downloadingView ? 'hourglass_top' : 'photo_camera'" x-small /></button>
									<button v-if="detail" class="tbtn" :class="{ on: octreeOn }" :disabled="buildingOctree"
										:title="octreeAvailable ? 'Full-resolution octree view (LOD-streamed)' : 'Build a full-resolution Potree octree on the host'"
										:style="octreeOn ? { background: '#0891b2', borderColor: '#0891b2' } : {}"
										@click="octreeAvailable ? (octreeMode = !octreeMode) : buildOctree()"><v-icon :name="buildingOctree ? 'hourglass_top' : 'blur_on'" x-small /> Full-res</button>
									<button v-if="detail && detail[`frm_${axis.toLowerCase()}`]" class="tbtn" title="Download this FRM image"
										@click="downloadFile(detail[`frm_${axis.toLowerCase()}`])"><v-icon name="download" x-small /></button>
									<button v-for="a in AXES" :key="a" class="tbtn" :class="{ on: axis === a }"
										:style="axis === a ? { background: AXIS_COLOR[a], borderColor: AXIS_COLOR[a] } : {}"
										@click="setAxis(a)">{{ a }}</button>
								</div>
							</div>
							<div class="frm-img">
								<div v-if="!detail" class="empty">Select an operation</div>
								<FrmOctree v-else-if="octreeOn" :octree-path="detail.octree_path" :axis="axis"
									:colormap="colormap" :point-size="pointSize" :cmin="cmin" :cmax="cmax" @climits="onClimits" />
								<FrmCloud v-else-if="liveOn" ref="frmCloudRef" :cache-file-id="detail.live_cache_file"
									:axis="axis" :feed="editFeed" :diam="editDiam" :speed-mode="speedMode"
									:rpm="editRpm" :vc="editVc" :time-scale="timeScale" :ppr="editPpr"
									:crop-start-sec="cropStartSec" :crop-end-sec="cropEndSec"
									:stride="plotStride" :gridding="gridding" :grid-n="gridN"
									:point-size="pointSize" :colormap="colormap" :cmin="cmin" :cmax="cmax"
									@loaded="onCloudLoaded" @climits="onClimits" />
								<div v-else-if="frmLoading" class="loading"><v-progress-circular indeterminate /></div>
								<img v-else-if="frmUrl" :src="frmUrl" :alt="`FRM ${axis}`" />
								<div v-else class="empty">No {{ axis }} fingerprint</div>
								<div v-if="downloadViewMsg" class="render-msg frm-render-msg">{{ downloadViewMsg }}</div>
								<div v-if="octreeMsg" class="render-msg frm-render-msg">{{ octreeMsg }}</div>
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
.col-stack .info:last-child { flex: 1 1 auto; min-height: 0; overflow-y: auto; }
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
.rowcard {
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
.statgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; }
.stat {
	background: var(--theme--background-subdued, #f7f9fb); border: 1px solid var(--theme--border-color-subdued, #e7ebf0);
	border-radius: 10px; padding: 9px 11px; display: flex; flex-direction: column; gap: 2px;
}
.s-top { display: flex; align-items: baseline; gap: 5px; flex-wrap: wrap; }
.s-val { font-size: 15px; font-weight: 750; letter-spacing: -0.01em; font-variant-numeric: tabular-nums; line-height: 1; }
.s-unit { font-size: 10px; font-weight: 600; color: var(--theme--foreground-subdued, #94a3b8); letter-spacing: 0.02em; }
.s-lab { font-size: 9.5px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--theme--foreground-subdued, #6b7684); font-weight: 600; }

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
.frm-img { flex: 1 1 auto; display: flex; align-items: center; justify-content: center; min-width: 0; min-height: 220px; overflow: hidden; }
.frm-img img { max-width: 100%; max-height: 100%; width: auto; height: auto; object-fit: contain; border-radius: 8px; border: 1px solid var(--theme--border-color-subdued, #e7ebf0); }
.layout.stacked .frm-img { min-height: 380px; }
.frm-img > .frm-cloud { align-self: stretch; }

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
.render-msg { margin-top: 7px; font-size: 11px; color: var(--theme--foreground-subdued, #6b7684); font-style: italic; }
</style>
