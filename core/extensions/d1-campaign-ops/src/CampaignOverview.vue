<script setup lang="ts">
/*
 * Overview of one campaign: its samples, operations and test sessions with counts, and each
 * machining operation's force-analysis (crawler/orchestrator) and diagnostics-build status, plus
 * pickers to add samples (campaign_samples junction) and test sessions (test_sessions.campaign_id).
 * Every read and write goes through the Directus API as the signed-in user, so their permissions
 * apply; a forbidden collection shows a note rather than failing the panel. The roll-up lives in
 * overview.js (unit tested). Design: docs/superpowers/specs/2026-10-06-sample-timeline-and-campaign-overview-design.md
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useApi } from '@directus/extensions-sdk';
// @ts-ignore plain JS module, tested with node --test
import { TEST_STATUS_ORDER, buildOverview, errMsg, isDuplicate, isForbidden } from './overview.js';

const props = defineProps<{ primaryKey: string | number; refreshKey?: number }>();
const api = useApi();

let unmounted = false;
let gen = 0;
const loading = ref(false);
const errors = ref<string[]>([]);       // one line per section that failed to load
const actionError = ref<string | null>(null);
const busy = ref<string | null>(null);

const junction = ref<any[]>([]);        // campaign_samples rows (with their own id, for removal)
const operations = ref<any[]>([]);
const tests = ref<any[]>([]);
const analyses = ref<any[]>([]);
const analysisUnavailable = ref(false); // the role may not read machining_force_analysis
const analysisFailed = ref(false);      // the read failed for another reason (listed in `errors`)
const noAnalysis = computed(() => analysisUnavailable.value || analysisFailed.value);

const ov = computed(() =>
	buildOverview({ samples: junction.value, operations: operations.value, tests: tests.value, analyses: analyses.value }),
);
const junctionIdBySample = computed(() => {
	const m = new Map<string, string>();
	for (const j of junction.value) {
		const sid = j.sample_id?.sample_id ?? j.sample_id;
		if (sid) m.set(sid, j.id);
	}
	return m;
});

async function list(collection: string, params: Record<string, unknown>): Promise<any[]> {
	const res = await api.get(`/items/${collection}`, { params });
	return res.data?.data ?? [];
}

async function load() {
	const g = ++gen;
	loading.value = true;
	const errs: string[] = [];
	const cid = props.primaryKey;
	const [j, o, t, a] = await Promise.allSettled([
		list('campaign_samples', { filter: { campaign_id: { _eq: cid } }, fields: ['id', 'sample_id.sample_id', 'sample_id.sample_code'], limit: -1 }),
		list('manufacturing_operations', {
			filter: { campaign_id: { _eq: cid } },
			fields: ['operation_id', 'pass_code', 'process_category', 'sample_id.sample_id', 'sample_id.sample_code'],
			sort: ['pass_code'],
			limit: -1,
		}),
		list('test_sessions', {
			filter: { campaign_id: { _eq: cid } },
			fields: ['session_id', 'test_type', 'status', 'session_date', 'sample_id.sample_id', 'sample_id.sample_code'],
			sort: ['-session_date'],
			limit: -1,
		}),
		list('machining_force_analysis', {
			filter: { operation_id: { campaign_id: { _eq: cid } } },
			fields: ['operation_id', 'status', 'error_message', 'diag_status', 'diag_error'],
			limit: -1,
		}),
	]);
	if (g !== gen || unmounted) return;
	const val = (r: PromiseSettledResult<any[]>, what: string) => {
		if (r.status === 'fulfilled') return r.value;
		errs.push(`Could not load ${what}: ${errMsg(r.reason)}`);
		return [];
	};
	junction.value = val(j, 'the sample list');
	operations.value = val(o, 'operations');
	tests.value = val(t, 'test sessions');
	// No access to the force-analysis table is a normal state for some roles: say so, don't alarm.
	// Any other failure (network, server) is a real error and is listed with the others.
	analysisUnavailable.value = a.status === 'rejected' && isForbidden(a.reason);
	analysisFailed.value = a.status === 'rejected' && !analysisUnavailable.value;
	analyses.value = analysisUnavailable.value ? [] : val(a, 'force-analysis status');
	errors.value = errs;
	loading.value = false;
}
onMounted(load);
watch(() => [props.primaryKey, props.refreshKey], load);
onBeforeUnmount(() => { unmounted = true; gen++; clearTimeout(sTimer); clearTimeout(tTimer); sGen++; tGen++; });

// ---- badges ----
const STATE_LABEL: Record<string, string> = {
	done: 'done', error: 'error', processing: 'processing', pending: 'pending', skipped: 'skipped', none: 'not analysed',
};
function stateClass(s: string) { return `st-${s}`; }
const testStatusChips = computed(() => {
	const by = ov.value.counts.testsByStatus as Record<string, number>;
	return Object.keys(by).sort((a, b) => TEST_STATUS_ORDER.indexOf(a) - TEST_STATUS_ORDER.indexOf(b)).map((k) => ({ k, n: by[k] }));
});
function fmtDate(d: string | null) {
	return d ? new Date(d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '—';
}

// ---- add samples ----
const sSearch = ref('');
const sResults = ref<any[]>([]);
const sSearching = ref(false);
let sTimer: any; let sGen = 0;
watch(sSearch, () => { clearTimeout(sTimer); sTimer = setTimeout(searchSamples, 250); });
async function searchSamples() {
	const g = ++sGen;
	const q = sSearch.value.trim();
	if (!q) { sResults.value = []; sSearching.value = false; return; }
	sSearching.value = true;
	try {
		const rows = await list('physical_samples', {
			filter: { _or: [{ sample_code: { _icontains: q } }, { nickname: { _icontains: q } }] },
			fields: ['sample_id', 'sample_code', 'nickname', 'material_id.common_name'],
			sort: ['sample_code'],
			limit: 40,
		});
		if (g !== sGen || unmounted) return;
		// Samples already in this campaign's list are not offered again.
		sResults.value = rows.filter((r) => !junctionIdBySample.value.has(r.sample_id)).slice(0, 25);
	} catch (e) {
		if (g !== sGen || unmounted) return;
		sResults.value = [];
		actionError.value = `Sample search failed: ${errMsg(e)}`;
	} finally { if (g === sGen) sSearching.value = false; }
}
async function addSample(id: string, code?: string | null) {
	if (busy.value) return;
	busy.value = id; actionError.value = null;
	try {
		await api.post('/items/campaign_samples', { campaign_id: props.primaryKey, sample_id: id });
		sResults.value = sResults.value.filter((r) => r.sample_id !== id);
	} catch (e) {
		actionError.value = `Could not add ${code || 'the sample'}: ${errMsg(e)}`;
	} finally { busy.value = null; }
	await load();
}
async function removeSample(id: string, code?: string | null) {
	const jid = junctionIdBySample.value.get(id);
	if (busy.value || !jid) return;
	busy.value = id; actionError.value = null;
	try {
		await api.delete(`/items/campaign_samples/${jid}`);
	} catch (e) {
		actionError.value = `Could not remove ${code || 'the sample'}: ${errMsg(e)}`;
	} finally { busy.value = null; }
	await load();
	searchSamples();
}

// ---- add test sessions ----
const tSearch = ref('');
const tResults = ref<any[]>([]);
const tSearching = ref(false);
let tTimer: any; let tGen = 0;
watch(tSearch, () => { clearTimeout(tTimer); tTimer = setTimeout(searchTests, 250); });
async function searchTests() {
	const g = ++tGen;
	const q = tSearch.value.trim();
	if (!q) { tResults.value = []; tSearching.value = false; return; }
	tSearching.value = true;
	try {
		const rows = await list('test_sessions', {
			// only sessions that are not in any campaign yet
			filter: { _and: [{ campaign_id: { _null: true } }, { _or: [{ test_type: { _icontains: q } }, { sample_id: { sample_code: { _icontains: q } } }] }] },
			fields: ['session_id', 'test_type', 'status', 'session_date', 'sample_id.sample_code'],
			sort: ['-session_date'],
			limit: 25,
		});
		if (g !== tGen || unmounted) return;
		tResults.value = rows;
	} catch (e) {
		if (g !== tGen || unmounted) return;
		tResults.value = [];
		actionError.value = `Test search failed: ${errMsg(e)}`;
	} finally { if (g === tGen) tSearching.value = false; }
}
async function setTestCampaign(id: string, campaign: string | number | null, label: string) {
	if (busy.value) return;
	busy.value = id; actionError.value = null;
	try {
		await api.patch(`/items/test_sessions/${id}`, { campaign_id: campaign });
		if (campaign) tResults.value = tResults.value.filter((r) => r.session_id !== id);
	} catch (e) {
		actionError.value = `Could not ${campaign ? 'add' : 'remove'} ${label}: ${errMsg(e)}`;
	} finally { busy.value = null; }
	await load();
	searchTests();
}
</script>

<template>
	<div class="ov">
		<div v-if="loading && !junction.length && !operations.length && !tests.length" class="ov-msg"><v-progress-circular indeterminate x-small /> loading overview…</div>
		<template v-else>
			<div v-for="e in errors" :key="e" class="ov-msg ov-err">{{ e }}</div>
			<div v-if="actionError" class="ov-msg ov-err">{{ actionError }}</div>

			<!-- counts + progress -->
			<div class="ov-cards">
				<div class="ov-card"><b>{{ ov.counts.samples }}</b><span>samples</span></div>
				<div class="ov-card"><b>{{ ov.counts.operations }}</b><span>operations</span></div>
				<div class="ov-card"><b>{{ ov.counts.tests }}</b><span>test sessions</span></div>
			</div>

			<div class="ov-prog">
				<div class="ov-prog-row">
					<span class="ov-prog-label">Force analysed</span>
					<div class="ov-bar" :title="`${ov.progress.analysed} of ${ov.progress.forceOps} machining operations analysed`"><i :style="{ width: ov.progress.analysedPct + '%' }" /></div>
					<span class="ov-prog-n">
						<template v-if="analysisUnavailable">not visible to your role</template>
						<template v-else-if="analysisFailed">could not load</template>
						<template v-else>{{ ov.progress.analysed }} / {{ ov.progress.forceOps }}</template>
					</span>
				</div>
				<div v-if="!noAnalysis" class="ov-prog-row">
					<span class="ov-prog-label">Diagnostics built</span>
					<div class="ov-bar ov-bar--diag"><i :style="{ width: ov.progress.diagBuiltPct + '%' }" /></div>
					<span class="ov-prog-n">{{ ov.progress.diagBuilt }} / {{ ov.progress.forceOps }}</span>
				</div>
				<div class="ov-prog-row">
					<span class="ov-prog-label">Tests complete</span>
					<div class="ov-bar ov-bar--test" title="Test sessions whose data is processed or analysed"><i :style="{ width: ov.progress.testsCompletePct + '%' }" /></div>
					<span class="ov-prog-n">{{ ov.progress.testsComplete }} / {{ ov.counts.tests }}</span>
				</div>
				<div v-if="testStatusChips.length" class="ov-chips">
					<span v-for="c in testStatusChips" :key="c.k" class="ov-pill" :class="`ts-${c.k}`">{{ c.n }} {{ c.k.replace(/_/g, ' ') }}</span>
				</div>
			</div>

			<!-- samples -->
			<h4>Samples ({{ ov.counts.samples }})</h4>
			<table v-if="ov.sampleRows.length" class="ov-table">
				<thead><tr><th>Sample</th><th class="n">Operations</th><th class="n">Tests</th><th></th></tr></thead>
				<tbody>
					<tr v-for="s in ov.sampleRows" :key="s.sample_id">
						<td>
							<router-link class="mono" :to="`/content/physical_samples/${s.sample_id}`">{{ s.sample_code || '—' }}</router-link>
							<span v-if="!s.member" class="ov-note" title="Has an operation or test in this campaign but is not in its sample list">not in list</span>
						</td>
						<td class="n">{{ s.operations }}</td>
						<td class="n">{{ s.tests }}</td>
						<td class="act">
							<button v-if="s.member" class="x" title="Remove from the campaign's sample list" :disabled="!!busy" @click="removeSample(s.sample_id, s.sample_code)"><v-icon name="close" x-small /></button>
							<button v-else class="x add" title="Add to the campaign's sample list" :disabled="!!busy" @click="addSample(s.sample_id, s.sample_code)"><v-icon name="add" x-small /></button>
						</td>
					</tr>
				</tbody>
			</table>
			<div v-else class="ov-empty">No samples yet.</div>
			<div class="ov-add">
				<div class="ov-add-head"><v-icon name="add" x-small /><input v-model="sSearch" class="ov-search" placeholder="Add samples by code or nickname…" /></div>
				<div v-if="sSearching" class="ov-msg sm"><v-progress-circular indeterminate x-small /> searching…</div>
				<div v-else-if="sResults.length" class="ov-results">
					<button v-for="r in sResults" :key="r.sample_id" class="ov-result" :disabled="!!busy" @click="addSample(r.sample_id, r.sample_code)">
						<span class="mono">{{ r.sample_code }}</span>
						<span class="ov-sub">{{ r.nickname || r.material_id?.common_name || '' }}</span>
						<v-icon name="add_circle" x-small />
					</button>
				</div>
				<div v-else-if="sSearch.trim()" class="ov-msg sm">No other samples match.</div>
			</div>

			<!-- operations + force status -->
			<h4>Operations and force analysis ({{ ov.counts.operations }})</h4>
			<table v-if="ov.opRows.length" class="ov-table">
				<thead><tr><th>Operation</th><th>Sample</th><th>Force analysis</th><th>Diagnostics</th></tr></thead>
				<tbody>
					<tr v-for="o in ov.opRows" :key="o.operation_id">
						<td><router-link class="mono" :to="`/content/manufacturing_operations/${o.operation_id}`">{{ o.pass_code || '—' }}</router-link></td>
						<td>{{ o.sample_code || '—' }}</td>
						<td>
							<span v-if="noAnalysis" class="ov-sub">—</span>
							<span v-else class="ov-pill" :class="stateClass(o.analysis)" :title="o.analysis_error || ''">{{ STATE_LABEL[o.analysis] }}</span>
						</td>
						<td>
							<span v-if="noAnalysis || o.diag === 'none'" class="ov-sub">—</span>
							<span v-else class="ov-pill" :class="stateClass(o.diag)" :title="o.diag_error || ''">{{ STATE_LABEL[o.diag] }}</span>
						</td>
					</tr>
				</tbody>
			</table>
			<div v-else class="ov-empty">No operations yet. Add them below.</div>

			<!-- tests -->
			<h4>Test sessions ({{ ov.counts.tests }})</h4>
			<table v-if="ov.testRows.length" class="ov-table">
				<thead><tr><th>Test</th><th>Sample</th><th>Date</th><th>Status</th><th></th></tr></thead>
				<tbody>
					<tr v-for="t in ov.testRows" :key="t.session_id">
						<td><router-link :to="`/content/test_sessions/${t.session_id}`">{{ t.test_type || '—' }}</router-link></td>
						<td>{{ t.sample_code || '—' }}</td>
						<td>{{ fmtDate(t.session_date) }}</td>
						<td><span class="ov-pill" :class="`ts-${t.status}`">{{ t.status ? t.status.replace(/_/g, ' ') : '—' }}</span></td>
						<td class="act"><button class="x" title="Remove from the campaign" :disabled="!!busy" @click="setTestCampaign(t.session_id, null, t.test_type || 'the test session')"><v-icon name="close" x-small /></button></td>
					</tr>
				</tbody>
			</table>
			<div v-else class="ov-empty">No test sessions yet.</div>
			<div class="ov-add">
				<div class="ov-add-head"><v-icon name="add" x-small /><input v-model="tSearch" class="ov-search" placeholder="Add test sessions by type or sample code…" /><span class="ov-filter">not in a campaign</span></div>
				<div v-if="tSearching" class="ov-msg sm"><v-progress-circular indeterminate x-small /> searching…</div>
				<div v-else-if="tResults.length" class="ov-results">
					<button v-for="r in tResults" :key="r.session_id" class="ov-result" :disabled="!!busy" @click="setTestCampaign(r.session_id, primaryKey, r.test_type || 'the test session')">
						<span class="mono">{{ r.test_type || '—' }}</span>
						<span class="ov-sub">{{ r.sample_id?.sample_code || '' }} · {{ fmtDate(r.session_date) }} · {{ r.status }}</span>
						<v-icon name="add_circle" x-small />
					</button>
				</div>
				<div v-else-if="tSearch.trim()" class="ov-msg sm">No unassigned test sessions match.</div>
			</div>
		</template>
	</div>
</template>

<style scoped>
.ov { font-size: 13px; margin-bottom: 16px; }
.ov h4 { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .5px; color: var(--theme--foreground-subdued, #64748b); margin: 16px 0 6px; }
.ov-msg { color: var(--theme--foreground-subdued, #6b7684); padding: 6px 2px; display: flex; align-items: center; gap: 6px; } .ov-msg.sm { font-size: 12px; padding: 5px 2px; }
.ov-err { color: #b91c1c; }
.ov-empty { color: var(--theme--foreground-subdued, #98a2b3); font-size: 12px; padding: 2px 0 6px; }
.ov-cards { display: flex; gap: 10px; flex-wrap: wrap; }
.ov-card { border: 1px solid var(--theme--border-color-subdued, #e7ebf0); background: var(--theme--background-subdued, #f7f9fb); border-radius: 10px; padding: 8px 16px; display: flex; flex-direction: column; align-items: center; min-width: 96px; }
.ov-card b { font-size: 22px; line-height: 1.1; } .ov-card span { font-size: 11px; color: var(--theme--foreground-subdued, #64748b); }
.ov-prog { margin-top: 12px; display: flex; flex-direction: column; gap: 6px; }
.ov-prog-row { display: flex; align-items: center; gap: 10px; }
.ov-prog-label { width: 120px; font-size: 12px; color: var(--theme--foreground-subdued, #64748b); }
.ov-bar { flex: 1 1 auto; max-width: 320px; height: 8px; border-radius: 99px; background: var(--theme--border-color-subdued, #e7ebf0); overflow: hidden; }
.ov-bar i { display: block; height: 100%; background: #2e7d32; border-radius: 99px; }
.ov-bar--diag i { background: #2563eb; } .ov-bar--test i { background: #6a1b9a; }
.ov-prog-n { font-size: 12px; font-variant-numeric: tabular-nums; }
.ov-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.ov-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.ov-table th { text-align: left; padding: 4px 6px; border-bottom: 1px solid var(--theme--border-color, #e2e8f0); color: var(--theme--foreground-subdued, #64748b); font-size: 11px; font-weight: 600; }
.ov-table td { padding: 4px 6px; border-bottom: 1px solid var(--theme--border-color-subdued, #eef1f5); }
.ov-table .n { text-align: right; font-variant-numeric: tabular-nums; width: 90px; }
.ov-table .act { width: 28px; text-align: right; }
.ov-table a { color: var(--theme--primary, #2563eb); text-decoration: none; } .ov-table a:hover { text-decoration: underline; }
.ov-table .x { border: 0; background: transparent; cursor: pointer; color: var(--theme--foreground-subdued, #94a3b8); border-radius: 5px; display: inline-flex; }
.ov-table .x:hover { color: #b91c1c; background: color-mix(in srgb, #b91c1c 10%, transparent); }
.ov-table .x.add:hover { color: #2563eb; background: color-mix(in srgb, #2563eb 10%, transparent); }
.ov-note { margin-left: 6px; font-size: 10px; color: #b45309; background: #fff7ed; padding: 1px 6px; border-radius: 99px; }
.ov-pill { font-size: 10px; font-weight: 600; padding: 1px 7px; border-radius: 99px; background: #eeeeee; color: #616161; white-space: nowrap; }
.st-done, .ts-processed, .ts-analysed { background: #e8f5e9; color: #2e7d32; }
.st-error, .ts-failed { background: #fce4ec; color: #c62828; }
.st-processing, .ts-processing, .ts-analysing { background: #e3f2fd; color: #1565c0; }
.st-pending, .ts-registered, .ts-pending_processing { background: #f3e5f5; color: #6a1b9a; }
.st-none, .st-skipped { background: #eeeeee; color: #616161; }
.ov-add { border: 1px dashed var(--theme--border-color, #d1d9e6); border-radius: 10px; padding: 8px 10px; margin-top: 8px; }
.ov-add-head { display: flex; align-items: center; gap: 6px; }
.ov-search { flex: 1 1 auto; border: 0; background: transparent; font: inherit; font-size: 13px; outline: none; color: var(--theme--foreground, #1e293b); }
.ov-filter { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; color: #2563eb; background: color-mix(in srgb, #2563eb 10%, transparent); padding: 2px 8px; border-radius: 99px; }
.ov-results { display: flex; flex-direction: column; gap: 3px; margin-top: 8px; max-height: 260px; overflow-y: auto; }
.ov-result { display: flex; align-items: center; gap: 8px; text-align: left; border: 1px solid var(--theme--border-color-subdued, #eef1f5); background: var(--theme--background, #fff); border-radius: 8px; padding: 5px 10px; cursor: pointer; }
.ov-result:hover { border-color: #2563eb; background: color-mix(in srgb, #2563eb 5%, transparent); }
.ov-sub { color: var(--theme--foreground-subdued, #6b7684); font-size: 11px; }
.ov-result .ov-sub { margin-left: auto; margin-right: 6px; }
.mono { font-family: var(--theme--fonts--monospace--font-family, 'SF Mono', Menlo, monospace); font-weight: 650; }
</style>
