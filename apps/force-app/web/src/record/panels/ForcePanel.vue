<script setup lang="ts">
// Force panel: Force (time-domain rolling envelope) or FFT (live Welch spectrum) of the FRM axis.
import { useWorkspace } from '../workspace';
import LiveForcePlot from '../LiveForcePlot.vue';
import LiveFft from '../LiveFft.vue';
const w = useWorkspace();
</script>

<template>
	<div class="force-panel">
		<div class="toggle">
			<button :class="{ on: w.plot.forceMode === 'time' }" @click="w.plot.forceMode = 'time'">Force</button>
			<button :class="{ on: w.plot.forceMode === 'fft' }" @click="w.plot.forceMode = 'fft'">FFT</button>
		</div>
		<div class="plot">
			<LiveForcePlot v-show="w.plot.forceMode === 'time'" :client="w.client" />
			<LiveFft v-show="w.plot.forceMode === 'fft'" :client="w.client" />
		</div>
	</div>
</template>

<style scoped>
.force-panel { display: flex; flex-direction: column; height: 100%; gap: 8px; }
.toggle { display: flex; gap: 4px; }
.toggle button { padding: 5px 12px; font-size: 12px; color: var(--text-dim); background: var(--surface); border: 1px solid var(--border); border-radius: 7px; cursor: pointer; }
.toggle button.on { background: var(--accent); color: var(--accent-ink); font-weight: 600; border-color: var(--accent); }
.plot { flex: 1; min-height: 0; position: relative; }
.plot > * { position: absolute; inset: 0; }
</style>
