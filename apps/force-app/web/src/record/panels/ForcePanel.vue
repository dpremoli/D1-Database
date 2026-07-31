<script setup lang="ts">
// Force panel: Force (time-domain rolling envelope) or FFT (live Welch spectrum) of the FRM axis.
import { useWorkspace } from '../workspace';
import LiveForcePlot from '../LiveForcePlot.vue';
import LiveFft from '../LiveFft.vue';
const w = useWorkspace();
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
.plot { flex: 1; min-height: 0; position: relative; }
.plot > * { position: absolute; inset: 0; }
</style>
