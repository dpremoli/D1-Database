<script setup lang="ts">
// The window/channel/mode controls here mirror ForcePanel.vue's toolbar deliberately — this route
// used to only read mode/channels/window from the opening URL once and never expose any way to
// change them afterward, so a pop-out was frozen at whatever was selected the moment it opened.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { RecordClient, SUB_NAMES } from './liveClient';
import { CH_COLOR } from './types';
import LiveForcePlot from './LiveForcePlot.vue';
import LiveFft from './LiveFft.vue';
import LiveSpectrogram from './LiveSpectrogram.vue';
import LiveWaterfall from './LiveWaterfall.vue';
import LiveFrm from './LiveFrm.vue';
import { defaultScale, type ColorScale } from '@d1/force-plotting';

const route = useRoute();
const panel = computed(() => String(route.params.panel || 'force'));
const isFrm = computed(() => panel.value === 'frm');
const isPolar = computed(() => panel.value === 'polar');

const q = new URLSearchParams(window.location.search);
const mode = ref<string>(q.get('mode') || 'time');
const SUMMED = ['Fx', 'Fy', 'Fz'];
const ORDER = [...SUMMED, ...SUB_NAMES];
const channels = ref<string[]>(q.get('channels')?.split(',').filter(Boolean) || [...SUMMED]);
const windowSec = ref(Number(q.get('window')) || 12);
const initColormap = ref<string>(q.get('colormap') || 'viridis');
const initPointSize = ref(Number(q.get('pointSize')) || 2.2);
const frmAxis = ref<'Fx' | 'Fy' | 'Fz'>((q.get('frmAxis') as 'Fx' | 'Fy' | 'Fz') || 'Fz');
const initStride = ref(Number(q.get('stride')) || 1);
// Polar pop-out: mirrors PolarPanel.vue's radius/angle-source selection so the two surfaces stay
// in sync when opened from the panel (query params carry the panel's current selection).
const polarRadius = ref<'Fz' | 'Fxy' | 'Mz'>((q.get('radius') as 'Fz' | 'Fxy' | 'Mz') || 'Fz');
const polarAngleSource = ref<'tacho' | 'force_vector'>((q.get('angle') as 'tacho' | 'force_vector') || 'tacho');

// #23: matches ForcePanel.vue/RecordPage.vue's own rename -- "Time" names the mode (raw
// time-domain, vs. FFT/Power/Spectrogram/Waterfall), not what's plotted on it, which isn't always
// force (Tacho, or a milling recording's Mz/X/Y/Z channels).
const MODES: { key: string; label: string }[] = [
	{ key: 'time', label: 'Time' }, { key: 'fft', label: 'FFT' }, { key: 'psd', label: 'Power' },
	{ key: 'spectrogram', label: 'Spectrogram' }, { key: 'waterfall', label: 'Waterfall' },
];
const MODE_LABEL: Record<string, string> = { time: 'Time Plot', fft: 'FFT', psd: 'Power', spectrogram: 'Spectrogram', waterfall: 'Waterfall' };
const title = computed(() => {
	if (isFrm.value) return 'Live FRM Fingerprint';
	if (isPolar.value) return 'Live Polar Plot';
	return 'Live ' + (MODE_LABEL[mode.value] || 'Time Plot');
});

const singleChannelMode = computed(() => mode.value === 'spectrogram' || mode.value === 'waterfall');
function toggleChannel(key: string) {
	if (singleChannelMode.value) { channels.value = [key]; return; }
	const s = channels.value.slice();
	const i = s.indexOf(key);
	if (i >= 0) { if (s.length > 1) s.splice(i, 1); } else s.push(key);
	channels.value = ORDER.filter((k) => s.includes(k));
}
// Matches ForcePanel.vue's guard (#32/#58): collapses a stale multi-selection when switching into,
// or opening the pop-out already in, spectrogram/waterfall mode -- a heatmap has nowhere to put a
// second channel, so what's ticked must always match what's shown.
watch(singleChannelMode, (single) => {
	if (single && channels.value.length > 1) channels.value = [channels.value[0]];
}, { immediate: true });
const subsOpen = ref(false);
const subCount = computed(() => channels.value.filter((k) => (SUB_NAMES as readonly string[]).includes(k)).length);

const client = new RecordClient();
// Clamped, matching the workspace path (workspace.ts). The number input below can be cleared to
// empty/NaN, and a non-positive window makes the rolling plot drop every point it is handed.
client.windowSec = Math.max(1, Number(windowSec.value) || 12);
watch(windowSec, (v) => { client.windowSec = Math.max(1, Number(v) || 12); });
const st = client.status;
const ready = computed(() => client.snapshotReady.value);
const colormap = ref(initColormap.value);
const pointSize = ref(initPointSize.value);
const maps = ['viridis', 'inferno', 'grayscale'];

// This pop-out's own FRM colour scale -- FULLY INDEPENDENT of whatever the main window's is doing
// (explicit design decision: a popped-out window can show the same live cut in a different colour
// scale for side-by-side comparison, not a mirrored read-only view). Its own local autoClimits, fed
// only by this LiveFrm instance's own climits event, never anything from the opener window; the
// only thing carried across at all is the initial colormap choice via the querystring, matching
// every other seed on this page (mode/channels/window/etc.).
const autoClimits = ref<{ cmin: number; cmax: number } | null>(null);
function onFrmClimits(v: { cmin: number; cmax: number }) {
	if (autoClimits.value && autoClimits.value.cmin === v.cmin && autoClimits.value.cmax === v.cmax) return;
	autoClimits.value = v;
}
const frmColorScale = computed<ColorScale>(() => ({
	...defaultScale(autoClimits.value?.cmin ?? 0, autoClimits.value?.cmax ?? 1),
	colormap: colormap.value,
}));

// Keeps the OS window title (taskbar/alt-tab) in sync with a mode change made after opening —
// onMounted alone only ever set it once, from the URL the window was opened with.
watch(title, (t) => { document.title = t; }, { immediate: true });

onMounted(() => { client.connectViaRelay(); });
onBeforeUnmount(() => client.disconnect());
</script>

<template>
	<div class="live-window">
		<header class="bar">
			<span class="rec-dot" :class="{ live: st.state === 'recording' }"></span>
			<span class="title">{{ title }}</span>
			<span class="state" :class="st.state">{{ st.state }}</span>
			<template v-if="isFrm">
				<div class="segmode">
					<button class="segbtn" :class="{ on: frmAxis === 'Fx' }" @click="frmAxis = 'Fx'">Fx</button>
					<button class="segbtn" :class="{ on: frmAxis === 'Fy' }" @click="frmAxis = 'Fy'">Fy</button>
					<button class="segbtn" :class="{ on: frmAxis === 'Fz' }" @click="frmAxis = 'Fz'">Fz</button>
				</div>
				<select v-model="colormap" class="cm"><option v-for="m in maps" :key="m">{{ m }}</option></select>
			</template>
			<template v-else-if="isPolar">
				<div class="segmode">
					<button v-for="r in (['Fz', 'Fxy', 'Mz'] as const)" :key="r" class="segbtn" :class="{ on: polarRadius === r }" @click="polarRadius = r">{{ r }}</button>
				</div>
				<select v-model="polarAngleSource" class="cm">
					<option value="tacho">Tacho</option>
					<option value="force_vector">atan2(Fy,Fx)</option>
				</select>
			</template>
			<template v-else>
				<div class="segmode">
					<button v-for="m in MODES" :key="m.key" class="segbtn" :class="{ on: mode === m.key }" @click="mode = m.key">{{ m.label }}</button>
				</div>
				<div class="chips">
					<button v-for="a in SUMMED" :key="a" class="chip" :style="channels.includes(a) ? { '--c': CH_COLOR[a] } : {}"
						:class="{ on: channels.includes(a) }" @click="toggleChannel(a)">{{ a }}</button>
				</div>
				<div class="subwrap">
					<button class="chip sub-btn" :class="{ on: subCount > 0 }" @click.stop="subsOpen = !subsOpen">
						Sub<span v-if="subCount"> · {{ subCount }}</span> <span class="material-symbols-rounded">expand_more</span>
					</button>
					<div v-if="subsOpen" class="subpop" @click.stop>
						<button v-for="s in SUB_NAMES" :key="s" class="subopt" :class="{ on: channels.includes(s) }" @click="toggleChannel(s)">
							<span class="dot" :style="{ background: CH_COLOR[s] }"></span>{{ s }}
							<span v-if="channels.includes(s)" class="material-symbols-rounded tick">check</span>
						</button>
					</div>
				</div>
				<span v-if="singleChannelMode" class="mono-hint" title="Spectrogram/waterfall show one channel">{{ channels[0] }} only</span>
				<div v-if="mode !== 'fft' && mode !== 'psd'" class="tw-row">
					<input type="range" min="2" max="60" step="1" v-model.number="windowSec" />
					<input type="number" min="1" max="300" v-model.number="windowSec" class="tw-num" />
					<span class="tw-unit">s</span>
				</div>
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
		<div class="body" @click="subsOpen = false">
			<div v-if="!ready" class="syncing">
				<span class="material-symbols-rounded spin">sync</span>
				<span>Syncing with parent…</span>
			</div>
			<template v-else>
				<LiveFrm v-if="isFrm" :client="client" :diam="80" :color-scale="frmColorScale" :point-size="pointSize" :point-stride="initStride" :axis="frmAxis"
					@climits="onFrmClimits" />
				<div v-else-if="isPolar" class="syncing">Polar pop-out shows a finished/replayed cut — open it from the embedded panel once a cut is done.</div>
				<LiveForcePlot v-else-if="mode === 'time'" :client="client" :channels="channels" />
				<LiveFft v-else-if="mode === 'fft' || mode === 'psd'" :client="client" :channels="channels" :scale="mode === 'psd' ? 'psd' : 'amp'" />
				<LiveSpectrogram v-else-if="mode === 'spectrogram'" :client="client" :channels="channels" :window-sec="windowSec" />
				<LiveWaterfall v-else-if="mode === 'waterfall'" :client="client" :channels="channels" :window-sec="windowSec" />
			</template>
		</div>
	</div>
</template>

<style scoped>
.live-window { position: fixed; inset: 0; display: flex; flex-direction: column; background: var(--bg); }
.bar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; row-gap: 8px; padding: 10px 16px; border-bottom: 1px solid var(--border); background: color-mix(in srgb, var(--bg) 90%, transparent); }
.rec-dot { width: 10px; height: 10px; border-radius: 50%; background: #64748b; flex-shrink: 0; }
.rec-dot.live { background: #ef4444; animation: pulse 1.4s infinite; }
@keyframes pulse { 50% { opacity: 0.4; } }
.title { font-weight: 600; font-size: 15px; flex-shrink: 0; }
.state { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-dim); flex-shrink: 0; }
.state.recording { color: #fbbf24; } .state.done { color: #4ade80; } .state.error { color: var(--danger); }
.cm { padding: 4px 8px; font-size: 12px; color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: 6px; }

/* Mode/channel controls — ported from record/panels/ForcePanel.vue's toolbar so behaviour and
   look stay identical between the embedded panel and its pop-out. */
.segmode { display: flex; gap: 4px; flex-shrink: 0; }
.segbtn { padding: 5px 10px; font-size: 12px; color: var(--text-dim); background: var(--surface); border: 1px solid var(--border); border-radius: 7px; cursor: pointer; }
.segbtn.on { background: var(--accent); color: var(--accent-ink); font-weight: 600; border-color: var(--accent); }
.chips { display: flex; gap: 5px; flex-shrink: 0; }
.chip { display: inline-flex; align-items: center; gap: 3px; padding: 4px 10px; font-size: 12px; font-weight: 600; color: var(--text-dim); background: var(--surface); border: 1px solid var(--border); border-radius: 999px; cursor: pointer; }
.chip.on { color: var(--c); border-color: var(--c); background: color-mix(in srgb, var(--c) 14%, transparent); }
.chip .material-symbols-rounded { font-size: 15px; }
.subwrap { position: relative; flex-shrink: 0; }
.sub-btn.on { --c: #38bdf8; color: #7dd3fc; border-color: #38bdf8; background: rgba(56,189,248,0.12); }
.subpop { position: absolute; top: 30px; left: 0; z-index: 40; min-width: 118px; background: var(--bg-2); border: 1px solid var(--border); border-radius: 9px; padding: 4px; box-shadow: 0 12px 34px rgba(0,0,0,0.3); }
.subopt { display: flex; align-items: center; gap: 7px; width: 100%; padding: 5px 7px; font-size: 12px; color: var(--text); background: transparent; border: none; border-radius: 6px; cursor: pointer; text-align: left; }
.subopt:hover { background: var(--surface-2); }
.subopt.on { color: #fff; }
.subopt .dot { width: 9px; height: 9px; border-radius: 50%; }
.subopt .tick { margin-left: auto; font-size: 14px; color: #4ade80; }
.mono-hint { font-family: var(--mono); font-size: 11px; color: var(--text-dim); background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 3px 7px; flex-shrink: 0; }
.tw-row { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
.tw-row input[type="range"] { width: 80px; accent-color: var(--accent); }
.tw-num { width: 42px !important; text-align: center; padding: 3px 2px !important; font-size: 11px !important; background: var(--surface); border: 1px solid var(--border); border-radius: 5px; color: var(--text); }
.tw-unit { font-size: 11px; color: var(--text-dim); }

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
