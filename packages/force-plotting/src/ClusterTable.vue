<script setup lang="ts">
// Per-cluster summary for the Diagnostics Workbench. Rows come from clusterStats(workingSet);
// the colour chip matches DiagScatter's cluster overlay. Clicking a row selects that cluster
// across the workbench (emit 'select'); clicking the active row again clears it.
import { clusterColorCss } from './clusterPalette';
import type { ClusterRow } from './selection';

const props = defineProps<{ rows: ClusterRow[]; activeId: number | null }>();
const emit = defineEmits<{ (e: 'select', id: number | null): void }>();

const fmt = (v: number, d = 2) => (Number.isFinite(v) ? v.toFixed(d) : '—');
const pct = (f: number) => `${(f * 100).toFixed(f < 0.01 ? 2 : 1)}%`;

function onRow(id: number) {
	emit('select', props.activeId === id ? null : id);
}
</script>

<template>
	<div class="cluster-table">
		<div v-if="!rows.length" class="ct-empty">no clusters — enable HDBSCAN in the recipe</div>
		<table v-else>
			<thead>
				<tr><th></th><th>cluster</th><th class="num">pts</th><th class="num">% cut</th>
					<th class="num">mean|z|</th><th class="num">max gi*</th><th class="num">r (mm)</th></tr>
			</thead>
			<tbody>
				<tr v-for="r in rows" :key="r.id"
					:class="{ active: r.id === activeId, noise: r.id < 0 }"
					@click="onRow(r.id)">
					<td><span class="chip" :style="{ background: clusterColorCss(r.id) }" /></td>
					<td>{{ r.id < 0 ? 'noise' : r.id }}</td>
					<td class="num">{{ r.n.toLocaleString() }}</td>
					<td class="num">{{ pct(r.fraction) }}</td>
					<td class="num">{{ fmt(r.meanAbsResidZ) }}</td>
					<td class="num">{{ fmt(r.maxGiStar) }}</td>
					<td class="num">{{ fmt(r.rMin, 1) }}–{{ fmt(r.rMax, 1) }}</td>
				</tr>
			</tbody>
		</table>
	</div>
</template>

<style scoped>
.cluster-table { font-size: 11px; overflow: auto; }
.ct-empty { padding: 10px 12px; color: var(--text-dim, #94a3b8); font-style: italic; }
table { width: 100%; border-collapse: collapse; }
th { text-align: left; font-weight: 600; font-size: 10px; text-transform: uppercase; letter-spacing: 0.03em; color: var(--text-dim, #94a3b8); padding: 4px 8px; border-bottom: 1px solid var(--border, rgba(255,255,255,0.12)); }
td { padding: 4px 8px; border-bottom: 1px solid var(--border, rgba(255,255,255,0.06)); color: var(--text, #e5e7eb); }
.num { text-align: right; font-variant-numeric: tabular-nums; }
tbody tr { cursor: pointer; }
tbody tr:hover { background: rgba(255,255,255,0.04); }
tbody tr.active { background: color-mix(in srgb, var(--accent, #38bdf8) 22%, transparent); }
tbody tr.noise td { color: var(--text-dim, #94a3b8); }
.chip { display: inline-block; width: 10px; height: 10px; border-radius: 3px; }
</style>
