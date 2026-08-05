<script setup lang="ts">
import { computed } from 'vue';
import { useWorkspace } from '../workspace';
const w = useWorkspace();
const st = w.st;
const estSizeMb = computed(() => {
	if (st.nTotal === 0) return 0;
	return st.nTotal * 10 * 8 / 1e6;
});
</script>

<template>
	<div class="overview">
		<div class="grid">
			<div class="ro"><span>State</span><b :class="st.state">{{ st.state }}</b></div>
			<div class="ro"><span>Elapsed</span><b>{{ st.tSec.toFixed(2) }}s</b></div>
			<div class="ro"><span>Cut</span><b :class="{ cut: st.cutStartSec !== null }">{{ st.cutStartSec !== null ? st.cutStartSec.toFixed(2) + 's' : '—' }}</b></div>
			<div class="ro"><span>RPM</span><b>{{ Math.round(st.rpm) }}</b></div>
			<div class="ro"><span>Samples</span><b>{{ st.nTotal.toLocaleString() }}</b></div>
			<div class="ro"><span>File size</span><b>{{ estSizeMb < 1 ? (estSizeMb * 1000).toFixed(0) + ' KB' : estSizeMb.toFixed(1) + ' MB' }}</b></div>
			<div class="ro"><span>Fx</span><b class="fx">{{ st.peaks.Fx.toFixed(1) }}</b></div>
			<div class="ro"><span>Fy</span><b class="fy">{{ st.peaks.Fy.toFixed(1) }}</b></div>
			<div class="ro"><span>Fz</span><b class="fz">{{ st.peaks.Fz.toFixed(1) }}</b></div>
		</div>
	</div>
</template>

<style scoped>
.overview { display: flex; flex-direction: column; height: 100%; justify-content: center; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(80px, 1fr)); gap: 8px; }
.ro { display: flex; flex-direction: column; align-items: center; padding: 6px 10px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; }
.ro span { font-size: 9.5px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.04em; }
.ro b { font-size: 14px; font-variant-numeric: tabular-nums; }
.ro b.recording { color: #fbbf24; } .ro b.done { color: #4ade80; } .ro b.error { color: var(--danger); }
.ro b.cut { color: #4ade80; }
.ro b.fx { color: #f87171; } .ro b.fy { color: #4ade80; } .ro b.fz { color: #60a5fa; }
</style>
