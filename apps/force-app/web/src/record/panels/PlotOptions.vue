<script setup lang="ts">
import { useWorkspace } from '../workspace';
const w = useWorkspace();
const axes = ['Fx', 'Fy', 'Fz'] as const;
const maps = ['viridis', 'inferno', 'grayscale'];
</script>

<template>
	<div class="plot-opts">
		<label>Colormap
			<select v-model="w.plot.colormap"><option v-for="m in maps" :key="m">{{ m }}</option></select>
		</label>
		<label>Point size <span class="val">{{ w.plot.pointSize.toFixed(1) }}</span>
			<input type="range" min="1" max="5" step="0.1" v-model.number="w.plot.pointSize" />
		</label>
		<p class="note">Axis drives the live FRM colour, the live FFT, and the captured fingerprint.</p>
	</div>
</template>

<style scoped>
.plot-opts { display: flex; flex-direction: column; gap: 14px; }
label { display: block; font-size: 11.5px; color: var(--text-dim); }
.seg { display: flex; gap: 4px; margin-top: 5px; }
.seg button { flex: 1; padding: 6px; font-size: 12px; color: var(--text-dim); background: var(--surface); border: 1px solid var(--border); border-radius: 7px; cursor: pointer; }
.seg button.on { background: var(--accent); color: var(--accent-ink); font-weight: 600; border-color: var(--accent); }
select { display: block; width: 100%; margin-top: 5px; padding: 7px 9px; font-size: 13px; color: var(--text); background: rgba(0,0,0,0.25); border: 1px solid var(--border); border-radius: 7px; }
input[type=range] { width: 100%; margin-top: 6px; accent-color: var(--accent); }
.val { color: var(--text); font-variant-numeric: tabular-nums; }
.note { font-size: 11px; color: var(--text-dim); opacity: 0.8; margin: 0; }
</style>
