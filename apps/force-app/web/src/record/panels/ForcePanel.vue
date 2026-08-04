<script setup lang="ts">
// Force panel: rolling force bands (Force) or a live Welch spectrum (FFT). The `inst` prop carries
// per-panel state — the selected channels (summed Fx/Fy/Fz and/or individual dyno sub-channels
// Fx1…Fz4) + the mode — so duplicated panels are independent (e.g. one showing only Fz1 to isolate
// a single sensor). Falls back to defaults (all summed axes, Force mode) for the detached window.
import { computed, ref } from 'vue';
import { useWorkspace } from '../workspace';
import LiveForcePlot from '../LiveForcePlot.vue';
import LiveFft from '../LiveFft.vue';
import LiveSpectrogram from '../LiveSpectrogram.vue';
import LiveWaterfall from '../LiveWaterfall.vue';
import { SUB_NAMES } from '../liveClient';
import { CH_COLOR } from '../types';
import { appUrl } from '../../appUrl';

type PlotMode = 'time' | 'fft' | 'psd' | 'spectrogram' | 'waterfall';
const MODES: { key: PlotMode; label: string }[] = [
	{ key: 'time', label: 'Force' }, { key: 'fft', label: 'FFT' }, { key: 'psd', label: 'Power' },
	{ key: 'spectrogram', label: 'Spectrogram' }, { key: 'waterfall', label: 'Waterfall' },
];
const props = defineProps<{ inst?: { mode?: PlotMode; channels?: string[]; axes?: string[] } }>();
const w = useWorkspace();
const SUMMED = ['Fx', 'Fy', 'Fz'];
const ORDER = [...SUMMED, ...SUB_NAMES];

const localMode = ref<PlotMode>('time');
const mode = computed<PlotMode>({
	get: () => props.inst?.mode ?? localMode.value,
	set: (v) => { if (props.inst) props.inst.mode = v; else localMode.value = v; },
});
// Spectrogram/waterfall render a single channel; hint the user which one is shown.
const singleChannelMode = computed(() => mode.value === 'spectrogram' || mode.value === 'waterfall');
const localCh = ref<string[]>([...SUMMED]);
const selected = computed<string[]>(() => props.inst?.channels ?? props.inst?.axes ?? localCh.value);
function setSel(next: string[]) {
	const ordered = ORDER.filter((k) => next.includes(k));
	if (props.inst) props.inst.channels = ordered; else localCh.value = ordered;
}
function toggle(key: string) {
	const s = selected.value.slice();
	const i = s.indexOf(key);
	if (i >= 0) { if (s.length > 1) s.splice(i, 1); } else s.push(key);
	setSel(s);
}
const subsOpen = ref(false);
const subCount = computed(() => selected.value.filter((k) => (SUB_NAMES as readonly string[]).includes(k)).length);
function openLive(panel: string) { window.open(appUrl(`/live/${panel}`), '_blank', 'noopener,width=1400,height=900'); }
</script>

<template>
	<div class="force-panel">
		<div class="controls">
			<div class="segmode">
				<button v-for="m in MODES" :key="m.key" class="segbtn" :class="{ on: mode === m.key }" @click="mode = m.key">{{ m.label }}</button>
			</div>
			<div class="chips">
				<button v-for="a in SUMMED" :key="a" class="chip" :style="selected.includes(a) ? { '--c': CH_COLOR[a] } : {}"
					:class="{ on: selected.includes(a) }" @click="toggle(a)">{{ a }}</button>
			</div>
			<div class="subwrap">
				<button class="chip sub-btn" :class="{ on: subCount > 0 }" @click.stop="subsOpen = !subsOpen">
					Sub<span v-if="subCount"> · {{ subCount }}</span> <span class="material-symbols-rounded">expand_more</span>
				</button>
				<div v-if="subsOpen" class="subpop" @click.stop>
					<button v-for="s in SUB_NAMES" :key="s" class="subopt" :class="{ on: selected.includes(s) }" @click="toggle(s)">
						<span class="dot" :style="{ background: CH_COLOR[s] }"></span>{{ s }}
						<span v-if="selected.includes(s)" class="material-symbols-rounded tick">check</span>
					</button>
				</div>
			</div>
			<span v-if="singleChannelMode" class="mono-hint" title="Spectrogram/waterfall show one channel">{{ selected[0] }} only</span>
			<button class="popout" title="Pop out to a new window (second monitor) — open before Start"
				@click="openLive(mode === 'time' ? 'force' : 'fft')">
				<span class="material-symbols-rounded">open_in_new</span>
			</button>
		</div>
		<div class="plot" @click="subsOpen = false">
			<LiveForcePlot v-show="mode === 'time'" :client="w.client" :channels="selected" />
			<LiveFft v-if="mode === 'fft' || mode === 'psd'" :client="w.client" :channels="selected" :scale="mode === 'psd' ? 'psd' : 'amp'" />
			<LiveSpectrogram v-else-if="mode === 'spectrogram'" :client="w.client" :channels="selected" />
			<LiveWaterfall v-else-if="mode === 'waterfall'" :client="w.client" :channels="selected" />
		</div>
	</div>
</template>

<style scoped>
.force-panel { display: flex; flex-direction: column; height: 100%; gap: 8px; }
.controls { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.segmode { display: flex; gap: 4px; }
.segbtn { padding: 5px 10px; font-size: 12px; color: var(--text-dim); background: var(--surface); border: 1px solid var(--border); border-radius: 7px; cursor: pointer; }
.segbtn.on { background: var(--accent); color: var(--accent-ink); font-weight: 600; border-color: var(--accent); }
.segbtn.fx.on { background: #f87171; border-color: #f87171; color: #2a0808; }
.segbtn.fy.on { background: #4ade80; border-color: #4ade80; color: #05210f; }
.segbtn.fz.on { background: #60a5fa; border-color: #60a5fa; color: #05173a; }
.chips { display: flex; gap: 5px; }
.chip { display: inline-flex; align-items: center; gap: 3px; padding: 4px 10px; font-size: 12px; font-weight: 600; color: var(--text-dim); background: var(--surface); border: 1px solid var(--border); border-radius: 999px; cursor: pointer; }
.chip.on { color: var(--c); border-color: var(--c); background: color-mix(in srgb, var(--c) 14%, transparent); }
.chip .material-symbols-rounded { font-size: 15px; }
.subwrap { position: relative; }
.sub-btn.on { --c: #38bdf8; color: #7dd3fc; border-color: #38bdf8; background: rgba(56,189,248,0.12); }
.subpop { position: absolute; top: 30px; left: 0; z-index: 40; min-width: 118px; background: #0f1730; border: 1px solid var(--border); border-radius: 9px; padding: 4px; box-shadow: 0 12px 34px rgba(0,0,0,0.5); }
.subopt { display: flex; align-items: center; gap: 7px; width: 100%; padding: 5px 7px; font-size: 12px; color: var(--text); background: transparent; border: none; border-radius: 6px; cursor: pointer; text-align: left; }
.subopt:hover { background: #16203c; }
.subopt.on { color: #fff; }
.subopt .dot { width: 9px; height: 9px; border-radius: 50%; }
.subopt .tick { margin-left: auto; font-size: 14px; color: #4ade80; }
.mono-hint { font-family: var(--mono); font-size: 11px; color: var(--text-dim); background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 3px 7px; }
.popout { margin-left: auto; display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: 7px; background: var(--surface); border: 1px solid var(--border); color: var(--text-dim); cursor: pointer; }
.popout:hover { color: var(--accent); background: var(--surface-2); }
.popout .material-symbols-rounded { font-size: 15px; }
.plot { flex: 1; min-height: 0; position: relative; }
.plot > * { position: absolute; inset: 0; }
</style>
