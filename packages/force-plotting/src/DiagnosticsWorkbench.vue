<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { GridLayout, GridItem } from 'grid-layout-plus';
import ForceChart from './ForceChart.vue';
import DiagOctreeView from './DiagOctreeView.vue';
import WorkbenchPanel from './WorkbenchPanel.vue';
import SelectionInspector from './SelectionInspector.vue';
import BandwidthStrip from './BandwidthStrip.vue';
import { fetchD1an } from './diagAttrs';
import { bucketEnvelope } from './liveCache';
import { computeStats, workingSetFromD1an } from './selection';
import type { Selection, WorkingSet } from './selection';
import { useForceHost } from './host';

const props = defineProps<{
	diagPath: string;
	diagMetrics: Record<string, unknown> | null;
	totalPoints: number;
}>();

const workingSet = ref<WorkingSet | null>(null);
const loadError = ref<string | null>(null);
const selection = ref<Selection>(null);
const channel = ref<'tsaResid' | 'residZ'>('residZ');

async function loadWorkingSet() {
	loadError.value = null;
	workingSet.value = null;
	try {
		const base = `${useForceHost().octreeUrl}/${props.diagPath}/`;
		const attrs = await fetchD1an(`${base}attrs.d1an`);
		workingSet.value = workingSetFromD1an(attrs);
	} catch (e: any) {
		loadError.value = e?.message || 'failed to load analysis attributes';
	}
}
onMounted(loadWorkingSet);
watch(() => props.diagPath, loadWorkingSet);

// ForceChart plots resid_z against time and doubles as the time-range brush -- its existing
// cropStart/cropEnd drag handles ARE the Panel A selection mechanism; no new brushing code is
// needed.
//
// ForceChart's `data` shape is kind-specific (confirmed by reading its `geom` computed):
// kind='env' reads `d.t` (x-axis) plus `d.min[i]`/`d.max[i]` (envelope bounds); kind='line'
// reads `d.f`/`d.amp[i]` instead. The crop-drag rendering (the shaded [cropStart,cropEnd]
// overlay this component relies on for the brush) is only implemented for kind='env' (see
// ForceChart.vue's `if (props.kind === 'env')` branch around its cropArea computation) --
// kind='line' has no equivalent. There is only one resid_z series here, not a min/max band,
// so min and max are set equal: `geom.area`'s stroke still renders at 0.6px width regardless
// of the band's height, so a degenerate envelope still reads as a visible line, not a blank
// fill.
//
// The x-axis MUST be ws.t (real time, seconds), not ws.rev: Selection{kind:'time'} and its
// tested matches()/computeStats() compare against ws.t, and ForceChart's cropStart/cropEnd
// are read back in the same units it was given on `d.t` -- plotting against revolution here
// while Selection means seconds would silently desynchronise the Panel A brush from what
// Panel B and the Inspector actually filter on.
//
// Bucketed via bucketEnvelope, not the raw WorkingSet (>=5M points, per the WorkingSet floor):
// ForceChart does no decimation of its own and rebuilds its SVG path from `data` on every
// crop-drag pointer frame, so feeding it one point per WorkingSet sample redraws a multi-MB
// path per frame. min===max per bucket collapses to the same degenerate-envelope case
// buildSeriesEnvelope already handles for a constant signal -- still a visible line, not blank.
const chartData = computed(() => {
	const ws = workingSet.value;
	if (!ws) return null;
	return bucketEnvelope(ws.t, ws.residZ);
});
function onCropStart(v: number) {
	const cur = selection.value;
	const t1 = cur && cur.kind === 'time' ? cur.t1 : (workingSet.value?.t.at(-1) ?? v);
	selection.value = { kind: 'time', t0: v, t1 };
}
function onCropEnd(v: number) {
	const cur = selection.value;
	const t0 = cur && cur.kind === 'time' ? cur.t0 : (workingSet.value?.t[0] ?? v);
	selection.value = { kind: 'time', t0, t1: v };
}

const stats = computed(() => (workingSet.value ? computeStats(workingSet.value, selection.value) : null));

const layout = ref([
	{ x: 0, y: 0, w: 7, h: 8, i: 'spatial' },
	{ x: 7, y: 0, w: 5, h: 8, i: 'signal' },
]);
</script>

<template>
	<div class="diag-workbench">
		<div v-if="loadError" class="dw-error">{{ loadError }}</div>
		<GridLayout v-model:layout="layout" :col-num="12" :row-height="40" :margin="[10, 10]" :is-resizable="true" :is-draggable="true">
			<GridItem v-for="item in layout" :key="item.i" :x="item.x" :y="item.y" :w="item.w" :h="item.h" :i="item.i" drag-allow-from=".wb-panel-handle">
				<WorkbenchPanel v-if="item.i === 'spatial'" title="Spatial" icon="scatter_plot">
					<DiagOctreeView
						:octree-path="props.diagPath"
						:channel="channel"
						colormap="viridis"
						:point-size="2.2"
						:total-points="props.totalPoints"
						:selection="selection"
					/>
					<template #footer>
						<select v-model="channel" class="dw-channel-select">
							<option value="residZ">resid_z (anomaly)</option>
							<option value="tsaResid">tsa_resid (residual)</option>
						</select>
					</template>
				</WorkbenchPanel>
				<WorkbenchPanel v-else-if="item.i === 'signal'" title="Signal" icon="show_chart">
					<ForceChart
						v-if="chartData"
						title="resid_z vs time"
						kind="env"
						:data="chartData"
						color="#f59e0b"
						x-unit="s"
						y-unit="σ"
						:crop-start="selection?.kind === 'time' ? selection.t0 : null"
						:crop-end="selection?.kind === 'time' ? selection.t1 : null"
						:crop-editable="true"
						@update:crop-start="onCropStart"
						@update:crop-end="onCropEnd"
					/>
					<div v-else class="dw-loading">loading…</div>
				</WorkbenchPanel>
			</GridItem>
		</GridLayout>
		<SelectionInspector v-if="stats" :stats="stats" />
		<BandwidthStrip :metrics="props.diagMetrics as any" />
	</div>
</template>

<style scoped>
.diag-workbench { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.diag-workbench :deep(.vgl-layout) { flex: 1; min-height: 0; }
.dw-error { padding: 8px 12px; color: var(--danger, #fca5a5); font-size: 12px; }
.dw-loading { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--text-dim); font-size: 12px; }
.dw-channel-select { width: 100%; font-size: 12px; padding: 4px 6px; background: var(--bg-2); color: var(--text, #e5e7eb); border: 1px solid var(--border); border-radius: 6px; }
</style>
