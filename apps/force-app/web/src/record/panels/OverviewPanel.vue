<script setup lang="ts">
import { computed } from 'vue';
import { useWorkspace } from '../workspace';
import { RAW_BYTES_PER_SAMPLE, RAW_COLUMNS } from '../liveClient';
import { formatBandwidth, formatDuration } from '../../format';
const w = useWorkspace();
const st = w.st;
const ROW_BYTES = RAW_COLUMNS * RAW_BYTES_PER_SAMPLE;

// Sub-second precision under a minute is a deliberate choice for this live tile (ticking
// "3.42s" reads as more alive than "0:03" while a cut is still short) — everything else here
// delegates to the shared formatter so a fix to the mm:ss/h:mm:ss logic doesn't need to be found
// and re-applied in three near-identical local copies.
function fmtTime(s: number): string {
	if (!Number.isFinite(s) || s < 0) return '—';
	if (s < 60) return s.toFixed(2) + 's';
	return formatDuration(s);
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
	return formatBandwidth((st.nTotal * ROW_BYTES) / st.tSec);
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
.ro span { font-size: 9px; color: var(--text-dim); letter-spacing: 0.01em; }
.ro b { font-size: 13px; font-variant-numeric: tabular-nums; white-space: nowrap; }
/* DESIGN TEST: `cut` is an identifier, not a status, and it was rendered in the Fy green sitting
   three tiles away in this same strip. Plain text -- only State keeps a status hue (a
   traffic light reads as status from context, which an axis identity does not). */
.ro b.recording { color: #fbbf24; } .ro b.done { color: #4ade80; } .ro b.error { color: var(--danger); }
.ro b.cut { color: var(--text); }
.ro b.eta { color: #fbbf24; }
.ro b.fx { color: #f87171; } .ro b.fy { color: #4ade80; } .ro b.fz { color: #60a5fa; }
</style>
