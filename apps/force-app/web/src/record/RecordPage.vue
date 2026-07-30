<script setup lang="ts">
// Recording orchestrator (slice 2a). Owns the RecordClient, drives the config → START → live →
// STOP → finished-cut flow. Live view uses LiveForcePlot + LiveFrm; the finished cut is rendered
// through the existing plotting FrmCloud (via its cacheOverride prop) from the backend's D1LC.
import { computed, onMounted, onBeforeUnmount, reactive, ref, shallowRef, watch } from 'vue';
import { useRouter } from 'vue-router';
import { RecordClient } from './liveClient';
import LiveForcePlot from './LiveForcePlot.vue';
import LiveFrm from './LiveFrm.vue';
import FrmCloud from '../force/FrmCloud.vue';
import { parseCache, type Cache } from '../force/liveCache';
import type { RecordConfig } from './types';

const router = useRouter();
const client = new RecordClient();
const st = client.status;

const cfg = reactive<Required<RecordConfig>>({
	sample_name: 'SIM-CUT-001',
	rpm: 1200,
	feed: 0.05,
	diam: 80,
	inner_diam: 0,
	sample_rate: 25000,
	duration_sec: 8,
	ppr: 1,
	axis: 'Fz',
});

const busy = ref(false);
const errMsg = ref<string | null>(null);
const finishedCache = shallowRef<Cache | null>(null);

const isIdle = computed(() => st.state === 'idle');
const isRecording = computed(() => st.state === 'recording');
const isFinalizing = computed(() => st.state === 'finalizing');
const isDone = computed(() => st.state === 'done');
const isError = computed(() => st.state === 'error');

async function start() {
	if (busy.value) return;
	busy.value = true; errMsg.value = null; finishedCache.value = null;
	try {
		await client.start({ ...cfg });
	} catch (e: any) {
		errMsg.value = e?.message || 'failed to start recording';
	} finally {
		busy.value = false;
	}
}

async function stop() {
	if (busy.value) return;
	busy.value = true;
	try {
		await client.stop();
		await loadFinished();
	} finally {
		busy.value = false;
	}
}

async function loadFinished() {
	const id = st.captureId;
	if (!id) return;
	try {
		const res = await fetch(client.cacheUrl(id));
		if (res.ok) finishedCache.value = parseCache(await res.arrayBuffer());
	} catch { /* finished view is best-effort */ }
}

// The sim can finish on its own (duration reached) — the backend sends a 'done' control frame.
// Load the finished cut on either path (manual Stop OR natural completion).
watch(() => st.state, (s) => { if (s === 'done' && !finishedCache.value) loadFinished(); });

function newRun() { client.reset(); finishedCache.value = null; errMsg.value = null; }
function matUrl() { return st.captureId ? `${client.cacheUrl(st.captureId).replace('live_cache.bin', 'capture.mat')}` : '#'; }

onMounted(() => client.connect());
onBeforeUnmount(() => client.disconnect());
</script>

<template>
	<div class="rec-wrap">
		<header class="topbar">
			<button class="back" @click="router.push('/select')"><span class="material-symbols-rounded">arrow_back</span></button>
			<div class="brand"><span class="rec-dot" :class="{ live: isRecording }"></span><span class="brand-name">Recording &amp; Acquisition</span></div>
			<div class="conn" :class="{ ok: st.connected }">
				<span class="material-symbols-rounded">{{ st.connected ? 'sensors' : 'sensors_off' }}</span>
				{{ st.connected ? 'stream connected' : 'stream offline' }}
			</div>
		</header>

		<main class="rec-main">
			<!-- config + controls -->
			<section class="panel config">
				<h3>Cut setup</h3>
				<label>Sample name<input v-model="cfg.sample_name" :disabled="isRecording || isFinalizing" /></label>
				<div class="grid2">
					<label>Spindle (RPM)<input type="number" v-model.number="cfg.rpm" :disabled="isRecording || isFinalizing" /></label>
					<label>Feed (mm/rev)<input type="number" step="0.01" v-model.number="cfg.feed" :disabled="isRecording || isFinalizing" /></label>
					<label>Outer Ø (mm)<input type="number" v-model.number="cfg.diam" :disabled="isRecording || isFinalizing" /></label>
					<label>Inner Ø (mm)<input type="number" v-model.number="cfg.inner_diam" :disabled="isRecording || isFinalizing" /></label>
					<label>Sample rate (Hz)<input type="number" v-model.number="cfg.sample_rate" :disabled="isRecording || isFinalizing" /></label>
					<label>Duration (s)<input type="number" v-model.number="cfg.duration_sec" :disabled="isRecording || isFinalizing" /></label>
					<label>Pulses/rev<input type="number" v-model.number="cfg.ppr" :disabled="isRecording || isFinalizing" /></label>
					<label>FRM axis
						<select v-model="cfg.axis" :disabled="isRecording || isFinalizing">
							<option>Fx</option><option>Fy</option><option>Fz</option>
						</select>
					</label>
				</div>

				<div class="actions">
					<button v-if="!isRecording && !isFinalizing" class="btn start" :disabled="busy || !st.connected" @click="start">
						<span class="material-symbols-rounded">fiber_manual_record</span> Start
					</button>
					<button v-else class="btn stop" :disabled="busy || isFinalizing" @click="stop">
						<span class="material-symbols-rounded">stop</span> {{ isFinalizing ? 'Finalizing…' : 'Stop' }}
					</button>
					<button v-if="isDone || isError" class="btn ghost" @click="newRun">New recording</button>
				</div>
				<p v-if="errMsg || isError" class="err">{{ errMsg || st.error }}</p>

				<div class="readouts">
					<div class="ro"><span>State</span><b :class="st.state">{{ st.state }}</b></div>
					<div class="ro"><span>Elapsed</span><b>{{ st.tSec.toFixed(2) }} s</b></div>
					<div class="ro"><span>RPM</span><b>{{ Math.round(st.rpm) }}</b></div>
					<div class="ro"><span>Samples</span><b>{{ st.nTotal.toLocaleString() }}</b></div>
					<div class="ro"><span>Peak Fx</span><b class="fx">{{ st.peaks.Fx.toFixed(1) }} N</b></div>
					<div class="ro"><span>Peak Fy</span><b class="fy">{{ st.peaks.Fy.toFixed(1) }} N</b></div>
					<div class="ro"><span>Peak Fz</span><b class="fz">{{ st.peaks.Fz.toFixed(1) }} N</b></div>
				</div>
			</section>

			<!-- live / finished view -->
			<section class="panel view">
				<template v-if="!isDone">
					<div class="view-head"><h3>Live force</h3><span v-if="isRecording" class="live-badge">● LIVE</span></div>
					<div class="live-force-wrap"><LiveForcePlot :client="client" /></div>
					<div class="view-head"><h3>Live FRM fingerprint</h3></div>
					<div class="live-frm-wrap"><LiveFrm :client="client" :diam="cfg.diam" /></div>
				</template>

				<template v-else>
					<div class="view-head">
						<h3>Captured fingerprint</h3>
						<a class="btn ghost sm" :href="matUrl()" download><span class="material-symbols-rounded">download</span> .mat</a>
					</div>
					<div class="finished-frm">
						<FrmCloud v-if="finishedCache" cache-file-id="" :cache-override="finishedCache"
							:axis="cfg.axis" :feed="finishedCache.feed" :diam="finishedCache.diam" :inner-diam="cfg.inner_diam"
							speed-mode="measured" :rpm="cfg.rpm" :vc="0" :time-scale="1" :ppr="cfg.ppr"
							:crop-start-sec="finishedCache.csSec" :crop-end-sec="finishedCache.ceSec"
							:stride="1" :gridding="false" :grid-n="600" :point-size="1.8" colormap="viridis" pane-label="captured" />
						<div v-else class="loading">Loading capture…</div>
					</div>
					<div v-if="st.summary" class="summary">
						Captured <b>{{ (st.summary.n || 0).toLocaleString() }}</b> samples ·
						peak Fz <b class="fz">{{ (st.summary.peaks?.Fz ?? 0).toFixed(1) }} N</b> ·
						saved to <code>{{ st.captureId }}</code>
					</div>
				</template>
			</section>
		</main>
	</div>
</template>

<style scoped>
.rec-wrap { min-height: 100vh; display: flex; flex-direction: column; background: radial-gradient(1200px 600px at 50% -10%, var(--bg-2), var(--bg)); }
.topbar { display: flex; align-items: center; gap: 14px; padding: 14px 20px; border-bottom: 1px solid var(--border); }
.back { display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 34px; border-radius: 9px; background: var(--surface); border: 1px solid var(--border); color: var(--text); cursor: pointer; }
.back:hover { background: var(--surface-2); }
.brand { display: flex; align-items: center; gap: 9px; }
.brand-name { font-weight: 600; }
.rec-dot { width: 10px; height: 10px; border-radius: 50%; background: #64748b; }
.rec-dot.live { background: #ef4444; box-shadow: 0 0 0 0 rgba(239,68,68,0.6); animation: pulse 1.4s infinite; }
@keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(239,68,68,0.5); } 70% { box-shadow: 0 0 0 8px rgba(239,68,68,0); } 100% { box-shadow: 0 0 0 0 rgba(239,68,68,0); } }
.conn { margin-left: auto; display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-dim); }
.conn.ok { color: #4ade80; }
.conn .material-symbols-rounded { font-size: 18px; }

.rec-main { flex: 1; display: grid; grid-template-columns: 340px 1fr; gap: 18px; padding: 18px 20px; }
@media (max-width: 820px) { .rec-main { grid-template-columns: 1fr; } }
.panel { background: rgba(17,26,51,0.6); border: 1px solid var(--border); border-radius: var(--radius); padding: 18px; }
.panel h3 { margin: 0 0 12px; font-size: 14px; font-weight: 640; }

.config label { display: block; font-size: 12px; color: var(--text-dim); margin-bottom: 10px; }
.config input, .config select { display: block; width: 100%; margin-top: 4px; padding: 8px 10px; font-size: 13.5px; color: var(--text); background: rgba(0,0,0,0.25); border: 1px solid var(--border); border-radius: 8px; outline: none; }
.config input:focus, .config select:focus { border-color: var(--accent); }
.config input:disabled, .config select:disabled { opacity: 0.55; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px; }

.actions { display: flex; gap: 10px; margin: 8px 0 4px; }
.btn { display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; font-size: 14px; font-weight: 600; border: none; border-radius: 9px; cursor: pointer; }
.btn .material-symbols-rounded { font-size: 19px; }
.btn.start { background: #22c55e; color: #05210f; }
.btn.stop { background: #ef4444; color: #2a0808; }
.btn.ghost { background: var(--surface); color: var(--text); border: 1px solid var(--border); }
.btn.ghost.sm { padding: 6px 11px; font-size: 12.5px; text-decoration: none; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.err { color: var(--danger); font-size: 12.5px; margin: 8px 0 0; }

.readouts { margin-top: 16px; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.ro { display: flex; justify-content: space-between; align-items: baseline; padding: 7px 10px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; }
.ro span { font-size: 11px; color: var(--text-dim); }
.ro b { font-size: 13px; font-variant-numeric: tabular-nums; }
.ro b.recording { color: #fbbf24; } .ro b.done { color: #4ade80; } .ro b.error { color: var(--danger); }
.ro b.fx { color: #f87171; } .ro b.fy { color: #4ade80; } .ro b.fz { color: #60a5fa; }

.view { display: flex; flex-direction: column; }
.view-head { display: flex; align-items: center; justify-content: space-between; margin: 4px 0 10px; }
.live-badge { color: #ef4444; font-size: 11px; font-weight: 700; letter-spacing: 0.05em; }
.live-force-wrap { height: 220px; margin-bottom: 16px; }
.live-frm-wrap { flex: 1; min-height: 320px; }
.finished-frm { flex: 1; min-height: 420px; }
.finished-frm > * { height: 100%; }
.loading { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--text-dim); }
.summary { margin-top: 12px; font-size: 13px; color: var(--text-dim); }
.summary code { color: var(--accent); }
.summary b.fz { color: #60a5fa; }
</style>
