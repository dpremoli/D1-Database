<script setup lang="ts">
// Force panel: rolling force bands (Force) or a live Welch spectrum (FFT). The `inst` prop carries
// per-panel state — the selected axes (channel selection for the graph) + the mode — so duplicated
// panels are independent (e.g. one showing only Fz to isolate it). Falls back to sensible defaults
// (all axes, Force mode) for the detached single-panel window.
import { computed, ref } from 'vue';
import { useWorkspace } from '../workspace';
import LiveForcePlot from '../LiveForcePlot.vue';
import LiveFft from '../LiveFft.vue';
import type { Axis } from '../types';

const props = defineProps<{ inst?: { mode?: 'time' | 'fft'; axes?: Axis[] } }>();
const w = useWorkspace();
const ALL: Axis[] = ['Fx', 'Fy', 'Fz'];

const localMode = ref<'time' | 'fft'>('time');
const mode = computed<'time' | 'fft'>({
	get: () => props.inst?.mode ?? localMode.value,
	set: (v) => { if (props.inst) props.inst.mode = v; else localMode.value = v; },
});
const localAxes = ref<Axis[]>([...ALL]);
const axes = computed<Axis[]>(() => props.inst?.axes ?? localAxes.value);
function toggleAxis(a: Axis) {
	const cur = axes.value.slice();
	const i = cur.indexOf(a);
	if (i >= 0) { if (cur.length > 1) cur.splice(i, 1); } else cur.push(a);
	const next = ALL.filter((x) => cur.includes(x));  // keep canonical order
	if (props.inst) props.inst.axes = next; else localAxes.value = next;
}
function openLive(panel: string) { window.open(`${location.origin}/live/${panel}`, '_blank', 'noopener,width=1400,height=900'); }
</script>

<template>
	<div class="force-panel">
		<div class="controls">
			<div class="segmode">
				<button class="segbtn" :class="{ on: mode === 'time' }" @click="mode = 'time'">Force</button>
				<button class="segbtn" :class="{ on: mode === 'fft' }" @click="mode = 'fft'">FFT</button>
			</div>
			<!-- Time: multi-select which axes to draw. FFT: single axis (drives the run's spectrum). -->
			<div v-if="mode === 'time'" class="chips">
				<button v-for="a in ALL" :key="a" class="chip" :class="[a.toLowerCase(), { on: axes.includes(a) }]" @click="toggleAxis(a)">{{ a }}</button>
			</div>
			<div v-else class="segmode">
				<button class="segbtn fx" :class="{ on: w.plot.frmAxis === 'Fx' }" @click="w.plot.frmAxis = 'Fx'">Fx</button>
				<button class="segbtn fy" :class="{ on: w.plot.frmAxis === 'Fy' }" @click="w.plot.frmAxis = 'Fy'">Fy</button>
				<button class="segbtn fz" :class="{ on: w.plot.frmAxis === 'Fz' }" @click="w.plot.frmAxis = 'Fz'">Fz</button>
			</div>
			<button class="popout" title="Pop out to a new window (second monitor) — open before Start"
				@click="openLive(mode === 'fft' ? 'fft' : 'force')">
				<span class="material-symbols-rounded">open_in_new</span>
			</button>
		</div>
		<div class="plot">
			<LiveForcePlot v-show="mode === 'time'" :client="w.client" :axes="axes" />
			<LiveFft v-show="mode === 'fft'" :client="w.client" />
		</div>
	</div>
</template>

<style scoped>
.force-panel { display: flex; flex-direction: column; height: 100%; gap: 8px; }
.controls { display: flex; gap: 8px; align-items: center; }
.segmode { display: flex; gap: 4px; }
.segbtn { padding: 5px 10px; font-size: 12px; color: var(--text-dim); background: var(--surface); border: 1px solid var(--border); border-radius: 7px; cursor: pointer; }
.segbtn.on { background: var(--accent); color: var(--accent-ink); font-weight: 600; border-color: var(--accent); }
.chips { display: flex; gap: 5px; }
.chip { padding: 4px 10px; font-size: 12px; font-weight: 600; color: var(--text-dim); background: var(--surface); border: 1px solid var(--border); border-radius: 999px; cursor: pointer; }
.chip.on.fx { color: #fca5a5; border-color: #f87171; background: rgba(248,113,113,0.14); }
.chip.on.fy { color: #86efac; border-color: #4ade80; background: rgba(74,222,128,0.14); }
.chip.on.fz { color: #93c5fd; border-color: #60a5fa; background: rgba(96,165,250,0.14); }
.popout { margin-left: auto; display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: 7px; background: var(--surface); border: 1px solid var(--border); color: var(--text-dim); cursor: pointer; }
.popout:hover { color: var(--accent); background: var(--surface-2); }
.popout .material-symbols-rounded { font-size: 15px; }
.plot { flex: 1; min-height: 0; position: relative; }
.plot > * { position: absolute; inset: 0; }
</style>
