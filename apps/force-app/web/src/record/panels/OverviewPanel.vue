<script setup lang="ts">
import { computed } from 'vue';
import { useWorkspace } from '../workspace';
import { RAW_BYTES_PER_SAMPLE, RAW_COLUMNS } from '../liveClient';
const w = useWorkspace();
const st = w.st;
const ROW_BYTES = RAW_COLUMNS * RAW_BYTES_PER_SAMPLE;

function fmtTime(s: number): string {
	if (!Number.isFinite(s) || s < 0) return '—';
	if (s < 60) return s.toFixed(2) + 's';
	const m = Math.floor(s / 60);
	const sec = Math.floor(s % 60);
	if (m < 60) return `${m}:${String(sec).padStart(2, '0')}`;
	const h = Math.floor(m / 60);
	const rm = m % 60;
	return `${h}:${String(rm).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
}

const estSizeMb = computed(() => {
	if (st.nTotal === 0) return 0;
	return st.nTotal * ROW_BYTES / 1e6;
});
function fmtSize(mb: number): string {
	if (mb < 1) return (mb * 1000).toFixed(0) + ' KB';
	if (mb < 1000) return mb.toFixed(1) + ' MB';
	return (mb / 1000).toFixed(2) + ' GB';
}

const bandwidth = computed(() => {
	if (st.tSec <= 0 || st.nTotal === 0) return '—';
	const bytesPerSec = (st.nTotal * ROW_BYTES) / st.tSec;
	if (bytesPerSec < 1e3) return (bytesPerSec).toFixed(0) + ' B/s';
	if (bytesPerSec < 1e6) return (bytesPerSec / 1e3).toFixed(1) + ' KB/s';
	return (bytesPerSec / 1e6).toFixed(2) + ' MB/s';
});

const eta = computed(() => {
	if (w.source.value === 'sim' && w.cfg.duration_sec > 0 && st.state === 'recording') {
		const remaining = w.cfg.duration_sec - st.tSec;
		return remaining > 0 ? fmtTime(remaining) : '0s';
	}
	return null;
});
</script>

<template>
	<div class="overview">
		<div class="grid">
			<div class="ro"><span>State</span><b :class="st.state">{{ st.state }}</b></div>
			<div class="ro"><span>Elapsed</span><b>{{ fmtTime(st.tSec) }}</b></div>
			<div class="ro" v-if="eta !== null"><span>ETA</span><b class="eta">{{ eta }}</b></div>
			<div class="ro"><span>Cut</span><b :class="{ cut: st.cutStartSec !== null }">{{ st.cutStartSec !== null ? fmtTime(st.cutStartSec) : '—' }}</b></div>
			<div class="ro"><span>RPM</span><b>{{ Math.round(st.rpm) }}</b></div>
			<div class="ro"><span>Samples</span><b>{{ st.nTotal.toLocaleString() }}</b></div>
			<div class="ro"><span>File size</span><b>{{ fmtSize(estSizeMb) }}</b></div>
			<div class="ro"><span>Bandwidth</span><b>{{ bandwidth }}</b></div>
			<div class="ro"><span>Fx</span><b class="fx">{{ st.peaks.Fx.toFixed(1) }}</b></div>
			<div class="ro"><span>Fy</span><b class="fy">{{ st.peaks.Fy.toFixed(1) }}</b></div>
			<div class="ro"><span>Fz</span><b class="fz">{{ st.peaks.Fz.toFixed(1) }}</b></div>
		</div>
	</div>
</template>

<style scoped>
.overview { display: flex; align-items: center; justify-content: center; height: 100%; }
.grid { display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; }
.ro { display: flex; flex-direction: column; align-items: center; padding: 3px 10px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; min-width: 68px; }
.ro span { font-size: 9px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.04em; }
.ro b { font-size: 13px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.ro b.recording { color: #fbbf24; } .ro b.done { color: #4ade80; } .ro b.error { color: var(--danger); }
.ro b.cut { color: #4ade80; }
.ro b.eta { color: #fbbf24; }
.ro b.fx { color: #f87171; } .ro b.fy { color: #4ade80; } .ro b.fz { color: #60a5fa; }
</style>
