<script setup lang="ts">
// A single live panel in its own window (for a second monitor). It opens its OWN WebSocket to the
// recorder, which broadcasts each frame to every connected client — so this window renders a live
// view of the SAME recording session driven from the main window. Open it BEFORE pressing Start so
// the FRM spiral accumulates from the beginning.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { RecordClient } from './liveClient';
import LiveForcePlot from './LiveForcePlot.vue';
import LiveFft from './LiveFft.vue';
import LiveFrm from './LiveFrm.vue';

const route = useRoute();
const panel = computed(() => String(route.params.panel || 'force')); // force | fft | frm
const title = computed(() => ({ force: 'Live Force', fft: 'Live FFT', frm: 'Live FRM Fingerprint' }[panel.value] || 'Live'));
const client = new RecordClient();
const st = client.status;
const colormap = ref('viridis');
const pointSize = ref(2.2);
const maps = ['viridis', 'inferno', 'grayscale'];

onMounted(() => { client.connect(); document.title = title.value; });
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
.bar { display: flex; align-items: center; gap: 12px; padding: 10px 16px; border-bottom: 1px solid var(--border); background: rgba(11,16,32,0.9); }
.rec-dot { width: 10px; height: 10px; border-radius: 50%; background: #64748b; }
.rec-dot.live { background: #ef4444; animation: pulse 1.4s infinite; }
@keyframes pulse { 50% { opacity: 0.4; } }
.title { font-weight: 600; font-size: 15px; }
.state { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-dim); }
.state.recording { color: #fbbf24; } .state.done { color: #4ade80; } .state.error { color: var(--danger); }
.cm { padding: 4px 8px; font-size: 12px; color: var(--text); background: rgba(0,0,0,0.25); border: 1px solid var(--border); border-radius: 6px; }
.conn { display: inline-flex; color: var(--text-dim); }
.conn.ok { color: #4ade80; }
.conn .material-symbols-rounded { font-size: 18px; }
.readouts { margin-left: auto; display: flex; align-items: baseline; gap: 6px; font-size: 12px; color: var(--text-dim); font-variant-numeric: tabular-nums; }
.readouts b { font-size: 15px; color: var(--text); }
.readouts b.fz { color: #60a5fa; }
.body { flex: 1; min-height: 0; padding: 12px; }
.body > * { height: 100%; }
</style>
