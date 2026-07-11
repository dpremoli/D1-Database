<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue';
import { useApi } from '@directus/extensions-sdk';

const api = useApi();

const loading = ref(true);
const state = ref<any | null>(null);       // force_crawler_state singleton
const queueCounts = ref<Record<string, number>>({});
const recent = ref<any[]>([]);
const errors = ref<any[]>([]);
const saving = ref(false);

// editable draft — only pushed to the server on Save, so typing doesn't fight
// the 5s poll overwriting the field mid-keystroke.
const draft = ref({
	workers: 2, throttle_seconds: 5, file_like: '', op_code_like: '',
	series_points: 3000, fft_points: 3000, frm_downsample_step: 5, frm_dpi: 300,
	live_cache_points: 250000, pulses_per_rev: 1,
});
const dirty = ref(false);

let timer: ReturnType<typeof setInterval> | undefined;

async function loadState() {
	const res = await api.get('/items/force_crawler_state');
	state.value = res.data.data;
	if (!dirty.value && state.value) {
		draft.value = {
			workers: state.value.workers,
			throttle_seconds: Number(state.value.throttle_seconds),
			file_like: state.value.file_like || '',
			op_code_like: state.value.op_code_like || '',
			series_points: state.value.series_points,
			fft_points: state.value.fft_points,
			frm_downsample_step: state.value.frm_downsample_step,
			frm_dpi: state.value.frm_dpi,
			live_cache_points: state.value.live_cache_points,
			pulses_per_rev: state.value.pulses_per_rev,
		};
	}
}

async function loadQueue() {
	const res = await api.get('/items/machining_force_analysis', {
		params: { aggregate: { count: '*' }, groupBy: ['status'] },
	});
	const counts: Record<string, number> = {};
	for (const row of res.data.data ?? []) counts[row.status] = Number(row.count);
	queueCounts.value = counts;
}

async function loadRecent() {
	const [rRes, eRes] = await Promise.all([
		api.get('/items/machining_force_analysis', {
			params: {
				filter: { status: { _in: ['done', 'error'] } },
				sort: '-updated_at', limit: 12,
				fields: ['id', 'status', 'error_message', 'updated_at', 'peak_fz',
					'operation_id.pass_code', 'operation_id.sample_id.sample_code'],
			},
		}),
		api.get('/items/machining_force_analysis', {
			params: {
				filter: { status: { _eq: 'error' } },
				sort: '-updated_at', limit: 20,
				fields: ['id', 'error_message', 'updated_at',
					'operation_id.pass_code', 'operation_id.sample_id.sample_code'],
			},
		}),
	]);
	recent.value = rRes.data.data ?? [];
	errors.value = eRes.data.data ?? [];
}

async function refreshAll() {
	await Promise.all([loadState(), loadQueue(), loadRecent()]);
}

onMounted(async () => {
	await refreshAll();
	loading.value = false;
	timer = setInterval(refreshAll, 5000);
});
onBeforeUnmount(() => { if (timer) clearInterval(timer); });

const isOnline = computed(() => {
	if (!state.value?.last_heartbeat_at) return false;
	return Date.now() - new Date(state.value.last_heartbeat_at).getTime() < 30_000;
});
const isRunning = computed(() => state.value?.desired_state === 'running');

async function toggleRunning() {
	const next = isRunning.value ? 'paused' : 'running';
	await api.patch('/items/force_crawler_state', { desired_state: next });
	await loadState();
}

async function saveSettings() {
	saving.value = true;
	try {
		await api.patch('/items/force_crawler_state', {
			workers: Number(draft.value.workers) || 1,
			throttle_seconds: Number(draft.value.throttle_seconds) || 0,
			file_like: draft.value.file_like || null,
			op_code_like: draft.value.op_code_like || null,
			series_points: Math.max(100, Number(draft.value.series_points) || 3000),
			fft_points: Math.max(100, Number(draft.value.fft_points) || 3000),
			frm_downsample_step: Math.max(1, Number(draft.value.frm_downsample_step) || 5),
			frm_dpi: Math.max(72, Number(draft.value.frm_dpi) || 300),
			live_cache_points: Math.max(1000, Number(draft.value.live_cache_points) || 250000),
			pulses_per_rev: Math.max(1, Number(draft.value.pulses_per_rev) || 1),
		});
		dirty.value = false;
		await loadState();
	} finally {
		saving.value = false;
	}
}

async function retryOne(id: string) {
	await api.patch(`/items/machining_force_analysis/${id}`, { status: 'pending', error_message: null });
	await refreshAll();
}
async function retryAllErrors() {
	await Promise.all(errors.value.map((e) => retryOne(e.id)));
}

// Recrawl: reprocess specific operations / a whole sample's operations (matched
// by operation or sample code) or everything tracked — resets status to
// 'pending' so the running daemon (or the next --run) picks them straight up.
const recrawlQuery = ref('');
const recrawling = ref(false);
const recrawlResult = ref<string | null>(null);

async function resetToPending(ids: string[]) {
	if (!ids.length) return 0;
	await api.patch('/items/machining_force_analysis', { keys: ids, data: { status: 'pending', error_message: null } });
	return ids.length;
}

async function recrawlMatching() {
	const q = recrawlQuery.value.trim();
	if (!q) return;
	recrawling.value = true;
	recrawlResult.value = null;
	try {
		const res = await api.get('/items/machining_force_analysis', {
			params: {
				filter: { _or: [
					{ 'operation_id.pass_code': { _icontains: q } },
					{ 'operation_id.sample_id.sample_code': { _icontains: q } },
				] },
				limit: -1,
				fields: ['id'],
			},
		});
		const ids = (res.data.data ?? []).map((r: any) => r.id);
		const n = await resetToPending(ids);
		recrawlResult.value = n ? `Queued ${n} file${n === 1 ? '' : 's'} matching "${q}"` : `No files match "${q}"`;
		await refreshAll();
	} finally {
		recrawling.value = false;
	}
}

async function recrawlAll() {
	if (!confirm(`Reprocess ALL ${totalQueued.value} tracked file(s)? This resets every row to pending.`)) return;
	recrawling.value = true;
	recrawlResult.value = null;
	try {
		const res = await api.get('/items/machining_force_analysis', { params: { limit: -1, fields: ['id'] } });
		const ids = (res.data.data ?? []).map((r: any) => r.id);
		const n = await resetToPending(ids);
		recrawlResult.value = `Queued all ${n} file(s)`;
		await refreshAll();
	} finally {
		recrawling.value = false;
	}
}

const STAT_ORDER = ['pending', 'processing', 'done', 'error', 'skipped'];
const STAT_COLOR: Record<string, string> = {
	pending: '#94a3b8', processing: '#d97706', done: '#16a34a', error: '#dc2626', skipped: '#64748b',
};
const stats = computed(() => STAT_ORDER.map((s) => ({ key: s, label: s, value: queueCounts.value[s] ?? 0 })));
const totalQueued = computed(() => Object.values(queueCounts.value).reduce((a, b) => a + b, 0));

function fmtTime(v: string | null) {
	if (!v) return '—';
	const d = new Date(v);
	return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
function opLabel(r: any) { return r.operation_id?.pass_code || r.operation_id?.sample_id?.sample_code || r.id; }
</script>

<template>
	<private-view title="Force Crawler">
		<div class="fc">
			<section class="hero">
				<div>
					<h1>Force Crawler</h1>
					<p>Host-side .mat processing queue · {{ totalQueued }} file{{ totalQueued === 1 ? '' : 's' }} tracked</p>
				</div>
			</section>

			<div v-if="loading" class="loading"><v-progress-circular indeterminate /></div>

			<template v-else>
				<div v-if="!isOnline" class="banner">
					<v-icon name="warning" small />
					<span>Daemon not detected (no heartbeat in the last 30s). Start it on the host:</span>
					<code>py scripts/force_orchestrator.py --daemon</code>
				</div>

				<div class="top-row">
					<!-- status card -->
					<div class="card status-card">
						<div class="status-head">
							<span class="dot" :class="{ on: isOnline }" />
							<span class="status-label">{{ isOnline ? 'Daemon online' : 'Daemon offline' }}</span>
							<button class="runbtn" :class="{ running: isRunning }" @click="toggleRunning">
								<v-icon :name="isRunning ? 'pause' : 'play_arrow'" x-small />
								{{ isRunning ? 'Pause' : 'Start' }}
							</button>
						</div>
						<div class="kv">
							<span>Desired state</span><span>{{ state?.desired_state ?? '—' }}</span>
							<span>PID</span><span>{{ state?.daemon_pid ?? '—' }}</span>
							<span>Started</span><span>{{ fmtTime(state?.daemon_started_at) }}</span>
							<span>Heartbeat</span><span>{{ fmtTime(state?.last_heartbeat_at) }}</span>
							<span>Last discover</span><span>{{ fmtTime(state?.last_discover_at) }}</span>
							<span>Activity</span><span class="activity">{{ state?.current_activity || '—' }}</span>
							<span>Session done / err</span><span>{{ state?.processed_count ?? 0 }} / {{ state?.error_count ?? 0 }}</span>
						</div>
					</div>

					<!-- queue stats -->
					<div class="stats">
						<div v-for="st in stats" :key="st.key" class="stat">
							<span class="s-val" :style="{ color: STAT_COLOR[st.key] }">{{ st.value }}</span>
							<span class="s-lab">{{ st.label }}</span>
						</div>
					</div>
				</div>

				<div class="mid-row">
					<!-- settings -->
					<div class="card settings">
						<div class="card-head"><v-icon name="tune" small /> Settings</div>
						<div class="form">
							<label>Workers<input v-model.number="draft.workers" type="number" min="1" max="16" @input="dirty = true" /></label>
							<label>Throttle (s)<input v-model.number="draft.throttle_seconds" type="number" min="0" step="0.5" @input="dirty = true" /></label>
							<label class="wide">File scope (ILIKE)<input v-model="draft.file_like" placeholder="%10-AA-MF%" @input="dirty = true" /></label>
							<label class="wide">Operation code scope (ILIKE)<input v-model="draft.op_code_like" placeholder="%MT-F%" @input="dirty = true" /></label>
						</div>
						<div class="form-sep">Sampling (applies to files processed after saving)</div>
						<div class="form">
							<label>Series points<input v-model.number="draft.series_points" type="number" min="100" step="100" @input="dirty = true" /></label>
							<label>FFT points<input v-model.number="draft.fft_points" type="number" min="100" step="100" @input="dirty = true" /></label>
							<label>FRM downsample (every Nth pt)<input v-model.number="draft.frm_downsample_step" type="number" min="1" step="1" @input="dirty = true" /></label>
							<label>FRM DPI<input v-model.number="draft.frm_dpi" type="number" min="72" step="6" @input="dirty = true" /></label>
						<label>Live cache points<input v-model.number="draft.live_cache_points" type="number" min="1000" step="1000" @input="dirty = true" /></label>
						<label>Pulses per rev<input v-model.number="draft.pulses_per_rev" type="number" min="1" step="1" @input="dirty = true" /></label>
						</div>
						<button class="savebtn" :disabled="!dirty || saving" @click="saveSettings">
							{{ saving ? 'Saving…' : 'Save settings' }}
						</button>

						<div class="form-sep">Recrawl</div>
						<div class="recrawl-row">
							<input v-model="recrawlQuery" class="recrawl-input" placeholder="Operation or sample code…"
								@keyup.enter="recrawlMatching" />
							<button class="recrawlbtn" :disabled="recrawling || !recrawlQuery.trim()" @click="recrawlMatching">Recrawl matches</button>
							<button class="recrawlbtn all" :disabled="recrawling" @click="recrawlAll">Recrawl all</button>
						</div>
						<div v-if="recrawlResult" class="recrawl-result">{{ recrawlResult }}</div>
					</div>

					<!-- errors -->
					<div class="card errors">
						<div class="card-head">
							<v-icon name="error_outline" small /> Errors
							<span class="chip">{{ errors.length }}</span>
							<button v-if="errors.length" class="retryall" @click="retryAllErrors">Retry all</button>
						</div>
						<div class="list">
							<div v-for="e in errors" :key="e.id" class="errrow">
								<div class="errrow-top">
									<span class="mono">{{ opLabel(e) }}</span>
									<button class="retrybtn" @click="retryOne(e.id)">Retry</button>
								</div>
								<div class="errmsg">{{ e.error_message || '—' }}</div>
							</div>
							<div v-if="!errors.length" class="empty">No errors 🎉</div>
						</div>
					</div>
				</div>

				<!-- activity feed -->
				<div class="card activity-card">
					<div class="card-head"><v-icon name="history" small /> Recent activity</div>
					<div class="list">
						<div v-for="r in recent" :key="r.id" class="actrow">
							<span class="dot2" :style="{ background: STAT_COLOR[r.status] }" />
							<span class="mono">{{ opLabel(r) }}</span>
							<span class="actstatus">{{ r.status }}</span>
							<span class="acttime">{{ fmtTime(r.updated_at) }}</span>
						</div>
						<div v-if="!recent.length" class="empty">No activity yet</div>
					</div>
				</div>
			</template>
		</div>
	</private-view>
</template>

<style scoped>
.fc {
	padding: 20px 24px 40px; max-width: 1200px; margin: 0 auto;
	font-family: var(--theme--fonts--sans--font-family, -apple-system, 'Segoe UI', Roboto, sans-serif);
	color: var(--theme--foreground, #1e293b);
}
.hero {
	border-radius: 18px; padding: 22px 26px; margin-bottom: 18px; color: #fff;
	background:
		radial-gradient(120% 140% at 100% 0%, rgba(255, 255, 255, 0.18), transparent 55%),
		linear-gradient(120deg, var(--theme--primary, #1d4ed8), #0d9488);
	box-shadow: 0 12px 30px -14px rgba(29, 78, 216, 0.5);
}
.hero h1 { margin: 0; font-size: 23px; font-weight: 750; letter-spacing: -0.01em; }
.hero p { margin: 5px 0 0; font-size: 13px; opacity: 0.9; }
.loading { display: grid; place-items: center; padding: 40px; }

.banner {
	display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
	background: color-mix(in srgb, #d97706 12%, transparent); border: 1px solid color-mix(in srgb, #d97706 30%, transparent);
	color: #92400e; border-radius: 12px; padding: 10px 14px; margin-bottom: 16px; font-size: 13px;
}
.banner code { background: #1e293b; color: #e2e8f0; padding: 2px 8px; border-radius: 6px; font-size: 12px; }

.card {
	background: var(--theme--background, #fff); border: 1px solid var(--theme--border-color-subdued, #e7ebf0);
	border-radius: 16px; padding: 16px 18px;
}
.card-head {
	display: flex; align-items: center; gap: 7px; font-size: 12px; font-weight: 700;
	text-transform: uppercase; letter-spacing: 0.05em; color: var(--theme--foreground-subdued, #6b7684); margin-bottom: 12px;
}

.top-row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; align-items: start; }
.status-card { display: flex; flex-direction: column; }
.status-head { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.dot { width: 9px; height: 9px; border-radius: 50%; background: #dc2626; flex: 0 0 auto; }
.dot.on { background: #16a34a; box-shadow: 0 0 0 3px color-mix(in srgb, #16a34a 20%, transparent); }
.status-label { font-size: 14px; font-weight: 700; flex: 1; }
.runbtn {
	display: inline-flex; align-items: center; gap: 4px; border: 0; cursor: pointer; font: inherit;
	font-size: 12px; font-weight: 700; padding: 6px 13px; border-radius: 9px; color: #fff; background: #16a34a;
}
.runbtn.running { background: #d97706; }
.kv { display: grid; grid-template-columns: auto 1fr; gap: 6px 12px; font-size: 12.5px; }
.kv span:nth-child(odd) { color: var(--theme--foreground-subdued, #6b7684); white-space: nowrap; }
.kv span:nth-child(even) { font-weight: 600; text-align: right; word-break: break-word; }
.activity { font-family: var(--theme--fonts--monospace--font-family, monospace); font-size: 11px; }

.stats { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
.stat {
	background: var(--theme--background-subdued, #f7f9fb); border: 1px solid var(--theme--border-color-subdued, #e7ebf0);
	border-radius: 14px; padding: 14px 8px; display: flex; flex-direction: column; align-items: center; gap: 4px; justify-content: center;
}
.s-val { font-size: 26px; font-weight: 780; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
.s-lab { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--theme--foreground-subdued, #6b7684); font-weight: 650; }

.mid-row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; align-items: start; }
.form-sep {
	font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
	color: var(--theme--foreground-subdued, #98a2b3); margin: 4px 0 8px;
	border-top: 1px solid var(--theme--border-color-subdued, #eef1f5); padding-top: 8px;
}
.form { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 12px; margin-bottom: 12px; }
.form label { display: flex; flex-direction: column; gap: 4px; font-size: 11.5px; font-weight: 600; color: var(--theme--foreground-subdued, #6b7684); }
.form label.wide { grid-column: 1 / -1; }
.form input {
	font: inherit; font-size: 13px; padding: 7px 10px; border-radius: 9px;
	border: 1px solid var(--theme--border-color-subdued, #e7ebf0); background: var(--theme--background, #fff); color: inherit;
}
.savebtn {
	font: inherit; font-size: 12.5px; font-weight: 700; cursor: pointer; border: 0; border-radius: 9px;
	padding: 7px 16px; color: #fff; background: var(--theme--primary, #1d4ed8);
}
.savebtn:disabled { opacity: 0.4; cursor: default; }

.recrawl-row { display: flex; gap: 8px; flex-wrap: wrap; }
.recrawl-input {
	flex: 1 1 160px; font: inherit; font-size: 13px; padding: 7px 10px; border-radius: 9px;
	border: 1px solid var(--theme--border-color-subdued, #e7ebf0); background: var(--theme--background, #fff); color: inherit;
}
.recrawlbtn {
	font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; border: 0; border-radius: 9px;
	padding: 7px 13px; color: var(--theme--primary, #1d4ed8); background: color-mix(in srgb, var(--theme--primary, #1d4ed8) 12%, transparent);
	white-space: nowrap;
}
.recrawlbtn.all { color: #b45309; background: color-mix(in srgb, #d97706 14%, transparent); }
.recrawlbtn:disabled { opacity: 0.45; cursor: default; }
.recrawl-result { margin-top: 8px; font-size: 11.5px; color: var(--theme--foreground-subdued, #6b7684); }

.errors .chip {
	font-size: 10px; font-weight: 700; color: #dc2626; background: color-mix(in srgb, #dc2626 12%, transparent);
	padding: 1px 7px; border-radius: 99px; margin-right: 8px;
}
.retryall { margin-left: auto; border: 0; background: none; cursor: pointer; font: inherit; font-size: 11px; font-weight: 700; color: var(--theme--primary, #1d4ed8); text-transform: none; letter-spacing: 0; }
.errors .list, .activity-card .list { max-height: 260px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.errrow { background: var(--theme--background-subdued, #f7f9fb); border-radius: 10px; padding: 8px 10px; }
.errrow-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.retrybtn {
	border: 0; cursor: pointer; font: inherit; font-size: 10.5px; font-weight: 700;
	color: var(--theme--primary, #1d4ed8); background: color-mix(in srgb, var(--theme--primary, #1d4ed8) 10%, transparent);
	padding: 2px 8px; border-radius: 7px;
}
.errmsg { font-size: 11px; color: #b91c1c; margin-top: 4px; word-break: break-word; }

.actrow { display: flex; align-items: center; gap: 10px; font-size: 12.5px; padding: 4px 2px; }
.dot2 { width: 7px; height: 7px; border-radius: 50%; flex: 0 0 auto; }
.actstatus { text-transform: uppercase; font-size: 10px; font-weight: 700; color: var(--theme--foreground-subdued, #6b7684); }
.acttime { margin-left: auto; font-size: 11px; color: var(--theme--foreground-subdued, #98a2b3); }

.mono { font-family: var(--theme--fonts--monospace--font-family, monospace); font-weight: 650; font-size: 12px; word-break: break-all; }
.empty { padding: 16px; text-align: center; color: var(--theme--foreground-subdued, #98a2b3); font-size: 12.5px; }

@media (max-width: 900px) {
	.top-row, .mid-row { grid-template-columns: 1fr; }
	.stats { grid-template-columns: repeat(5, 1fr); }
}
</style>
