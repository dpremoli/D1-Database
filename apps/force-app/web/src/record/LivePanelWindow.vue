<script setup lang="ts">
// A single live panel in its own window (for a second monitor). Connects via BroadcastChannel relay
// to the main window's RecordClient, so it shares the same accumulated state — the FRM spiral,
// force traces, and FFT history all mirror the parent. A snapshot of the parent's current buffers
// is sent on open so even a mid-recording pop-out catches up immediately.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { RecordClient } from './liveClient';
import LiveForcePlot from './LiveForcePlot.vue';
import LiveFft from './LiveFft.vue';
import LiveFrm from './LiveFrm.vue';

const route = useRoute();
const panel = computed(() => String(route.params.panel || 'force'));
const title = computed(() => ({ force: 'Live Force', fft: 'Live FFT', frm: 'Live FRM Fingerprint' }[panel.value] || 'Live'));
const client = new RecordClient();
const st = client.status;
const colormap = ref('viridis');
const pointSize = ref(2.2);
const maps = ['viridis', 'inferno', 'grayscale'];

onMounted(() => { client.connectViaRelay(); document.title = title.value; });
onBeforeUnmount(() => client.disconnect());
</script>

<template>
	<div class="live-window">
		<header class="bar">
			<span class="rec-dot" :class="{ live: st.state === 'recording' }"></span>
			<span class="title">{{ title }}</span>
			<span class="state" :class="st.state">{{ st.state }}</span>
			<template v-if="panel === 'frm'">
				<select v-model="colormap" class="cm"><option v-for="m in maps" :key="m">{{ m }}</option></select>
			</template>
			<span class="conn" :class="{ ok: st.connected }">
				<span class="material-symbols-rounded">{{ st.connected ? 'sensors' : 'sensors_off' }}</span>
			</span>
			<div class="readouts">
				<template v-if="st.cutStartSec !== null"><b class="cut">&#x2713; cut</b><span>{{ st.cutStartSec.toFixed(2) }}s</span></template>
				<b>{{ Math.round(st.rpm) }}</b><span>rpm</span>
				<b class="fz">{{ st.peaks.Fz.toFixed(0) }}</b><span>Fz peak</span>
			</div>
		</header>
		<div class="body">
			<LiveForcePlot v-if="panel === 'force'" :client="client" />
			<LiveFft v-else-if="panel === 'fft'" :client="client" />
			<LiveFrm v-else :client="client" :diam="80" :colormap="colormap" :point-size="pointSize" />
		</div>
	</div>
</template>

<style scoped>
.live-window { position: fixed; inset: 0; display: flex; flex-direction: column; background: var(--bg); }
.bar { display: flex; align-items: center; gap: 12px; padding: 10px 16px; border-bottom: 1px solid var(--border); background: color-mix(in srgb, var(--bg) 90%, transparent); }
.rec-dot { width: 10px; height: 10px; border-radius: 50%; background: #64748b; }
.rec-dot.live { background: #ef4444; animation: pulse 1.4s infinite; }
@keyframes pulse { 50% { opacity: 0.4; } }
.title { font-weight: 600; font-size: 15px; }
.state { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-dim); }
.state.recording { color: #fbbf24; } .state.done { color: #4ade80; } .state.error { color: var(--danger); }
.cm { padding: 4px 8px; font-size: 12px; color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: 6px; }
.conn { display: inline-flex; color: var(--text-dim); }
.conn.ok { color: #4ade80; }
.conn .material-symbols-rounded { font-size: 18px; }
.readouts { margin-left: auto; display: flex; align-items: baseline; gap: 6px; font-size: 12px; color: var(--text-dim); font-variant-numeric: tabular-nums; }
.readouts b { font-size: 15px; color: var(--text); }
.readouts b.fz { color: #60a5fa; }
.readouts b.cut { color: #4ade80; font-size: 13px; }
.body { flex: 1; min-height: 0; padding: 12px; overflow: hidden; }
.body > * { height: 100%; }
</style>
