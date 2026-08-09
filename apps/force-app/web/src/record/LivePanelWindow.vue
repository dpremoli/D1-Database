<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { RecordClient } from './liveClient';
import LiveForcePlot from './LiveForcePlot.vue';
import LiveFft from './LiveFft.vue';
import LiveSpectrogram from './LiveSpectrogram.vue';
import LiveWaterfall from './LiveWaterfall.vue';
import LiveFrm from './LiveFrm.vue';

const route = useRoute();
const panel = computed(() => String(route.params.panel || 'force'));
const isFrm = computed(() => panel.value === 'frm');

const q = new URLSearchParams(window.location.search);
const initMode = ref<string>(q.get('mode') || 'time');
const initChannels = ref<string[]>(q.get('channels')?.split(',').filter(Boolean) || ['Fx', 'Fy', 'Fz']);
const windowSec = ref(Number(q.get('window')) || 12);
const initColormap = ref<string>(q.get('colormap') || 'viridis');
const initPointSize = ref(Number(q.get('pointSize')) || 2.2);
const initFrmAxis = ref<string>(q.get('frmAxis') || 'Fz');
const initStride = ref(Number(q.get('stride')) || 1);

const MODE_LABEL: Record<string, string> = { time: 'Force Plot', fft: 'FFT', psd: 'Power', spectrogram: 'Spectrogram', waterfall: 'Waterfall' };
const title = computed(() => {
	if (isFrm.value) return 'Live FRM Fingerprint';
	return 'Live ' + (MODE_LABEL[initMode.value] || 'Force');
});

const client = new RecordClient();
client.windowSec = windowSec.value;
const st = client.status;
const ready = computed(() => client.snapshotReady.value);
const colormap = ref(initColormap.value);
const pointSize = ref(initPointSize.value);
const maps = ['viridis', 'inferno', 'grayscale'];

onMounted(() => { client.connectViaRelay(); document.title = title.value; });
onBeforeUnmount(() => client.disconnect());
</script>

<template>
	<div class="live-window">
		<header class="bar">
			<span class="rec-dot" :class="{ live: st.state === 'recording' }"></span>
			<span class="title">{{ title }}</span>
			<span v-if="!isFrm && initChannels.join() !== 'Fx,Fy,Fz'" class="ch-hint">{{ initChannels.join(' ') }}</span>
			<span class="state" :class="st.state">{{ st.state }}</span>
			<template v-if="isFrm">
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
			<div v-if="!ready" class="syncing">
				<span class="material-symbols-rounded spin">sync</span>
				<span>Syncing with parent…</span>
			</div>
			<template v-else>
				<LiveFrm v-if="isFrm" :client="client" :diam="80" :colormap="colormap" :point-size="pointSize" :point-stride="initStride" />
				<LiveForcePlot v-else-if="initMode === 'time'" :client="client" :channels="initChannels" />
				<LiveFft v-else-if="initMode === 'fft' || initMode === 'psd'" :client="client" :channels="initChannels" :scale="initMode === 'psd' ? 'psd' : 'amp'" />
				<LiveSpectrogram v-else-if="initMode === 'spectrogram'" :client="client" :channels="initChannels" :window-sec="windowSec" />
				<LiveWaterfall v-else-if="initMode === 'waterfall'" :client="client" :channels="initChannels" :window-sec="windowSec" />
			</template>
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
.ch-hint { font-size: 11px; color: var(--text-dim); font-family: var(--mono); background: var(--surface); border: 1px solid var(--border); border-radius: 5px; padding: 2px 6px; }
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
.syncing { display: flex; align-items: center; justify-content: center; gap: 8px; height: 100%; color: var(--text-dim); font-size: 13px; }
.spin { animation: sp 1s linear infinite; }
@keyframes sp { to { transform: rotate(360deg); } }
.body { flex: 1; min-height: 0; padding: 12px; overflow: hidden; }
.body > * { height: 100%; }
</style>
