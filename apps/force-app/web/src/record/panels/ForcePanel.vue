<script setup lang="ts">
// Force panel: Force (time-domain rolling envelope) or FFT (live Welch spectrum) of the FRM axis.
import { useWorkspace } from '../workspace';
import LiveForcePlot from '../LiveForcePlot.vue';
import LiveFft from '../LiveFft.vue';
const w = useWorkspace();
function openLive(panel: string) { window.open(`${location.origin}/live/${panel}`, '_blank', 'noopener,width=1400,height=900'); }
</script>

<template>
	<div class="force-panel">
		<div class="controls">
			<div class="segmode">
				<button class="segbtn" :class="{ on: w.plot.forceMode === 'time' }" @click="w.plot.forceMode = 'time'">Force</button>
				<button class="segbtn" :class="{ on: w.plot.forceMode === 'fft' }" @click="w.plot.forceMode = 'fft'">FFT</button>
			</div>
			<div v-if="w.plot.forceMode === 'fft'" class="segmode">
				<button class="segbtn fx" :class="{ on: w.plot.frmAxis === 'Fx' }" @click="w.plot.frmAxis = 'Fx'">Fx</button>
				<button class="segbtn fy" :class="{ on: w.plot.frmAxis === 'Fy' }" @click="w.plot.frmAxis = 'Fy'">Fy</button>
				<button class="segbtn fz" :class="{ on: w.plot.frmAxis === 'Fz' }" @click="w.plot.frmAxis = 'Fz'">Fz</button>
			</div>
			<button class="popout" title="Pop out to a new window (second monitor) — open before Start"
				@click="openLive(w.plot.forceMode === 'fft' ? 'fft' : 'force')">
				<span class="material-symbols-rounded">open_in_new</span>
			</button>
		</div>
		<div class="plot">
			<LiveForcePlot v-show="w.plot.forceMode === 'time'" :client="w.client" />
			<LiveFft v-show="w.plot.forceMode === 'fft'" :client="w.client" />
		</div>
	</div>
</template>

<style scoped>
.force-panel { display: flex; flex-direction: column; height: 100%; gap: 8px; }
.controls { display: flex; gap: 8px; align-items: center; }
.popout { margin-left: auto; display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: 7px; background: var(--surface); border: 1px solid var(--border); color: var(--text-dim); cursor: pointer; }
.popout:hover { color: var(--accent); background: var(--surface-2); }
.popout .material-symbols-rounded { font-size: 15px; }
.plot { flex: 1; min-height: 0; position: relative; }
.plot > * { position: absolute; inset: 0; }
</style>
