<script setup lang="ts">
// Modular Recording workspace: a draggable/resizable grid of panels (Recording Options, Metadata,
// Force Plot w/ FFT, FRM Map, Plot Options), mirroring the Directus force-analysis feel. Layout is
// persisted to localStorage; panels share one workspace store via provide/inject.
import { onMounted, onBeforeUnmount, provide, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { GridLayout, GridItem } from 'grid-layout-plus';
import { createWorkspace, WORKSPACE } from './workspace';
import PanelFrame from './panels/PanelFrame.vue';
import RecordingOptions from './panels/RecordingOptions.vue';
import MetadataPanel from './panels/MetadataPanel.vue';
import ForcePanel from './panels/ForcePanel.vue';
import FrmPanel from './panels/FrmPanel.vue';
import PlotOptions from './panels/PlotOptions.vue';

const router = useRouter();
const w = createWorkspace();
provide(WORKSPACE, w);
const st = w.st;

const PANELS: Record<string, { title: string; icon: string }> = {
	options: { title: 'Recording Options', icon: 'tune' },
	metadata: { title: 'Metadata', icon: 'description' },
	force: { title: 'Force Plot', icon: 'show_chart' },
	frm: { title: 'FRM Map', icon: 'fingerprint' },
	plotopts: { title: 'Plot Options', icon: 'palette' },
};
const DEFAULT_LAYOUT = [
	{ i: 'options', x: 0, y: 0, w: 3, h: 11 },
	{ i: 'metadata', x: 0, y: 11, w: 3, h: 9 },
	{ i: 'force', x: 3, y: 0, w: 5, h: 10 },
	{ i: 'plotopts', x: 3, y: 10, w: 5, h: 10 },
	{ i: 'frm', x: 8, y: 0, w: 4, h: 20 },
];
const LS_KEY = 'force-app.record.layout';

function loadLayout() {
	try {
		const s = JSON.parse(localStorage.getItem(LS_KEY) || 'null');
		if (Array.isArray(s) && s.length === DEFAULT_LAYOUT.length) return s;
	} catch { /* fall through */ }
	return DEFAULT_LAYOUT.map((x) => ({ ...x }));
}
const layout = ref(loadLayout());
let saveT: any = null;
watch(layout, (l) => { clearTimeout(saveT); saveT = setTimeout(() => localStorage.setItem(LS_KEY, JSON.stringify(l)), 400); }, { deep: true });
function resetLayout() { layout.value = DEFAULT_LAYOUT.map((x) => ({ ...x })); }

// Load the finished cut on manual stop OR natural completion.
watch(() => st.state, (s) => { if (s === 'done' && !w.finishedCache.value) w.loadFinished(); });

onMounted(() => w.client.connect());
onBeforeUnmount(() => w.client.disconnect());
</script>

<template>
	<div class="rec-wrap">
		<header class="topbar">
			<button class="back" @click="router.push('/select')"><span class="material-symbols-rounded">arrow_back</span></button>
			<div class="brand"><span class="rec-dot" :class="{ live: w.isRecording.value }"></span><span class="brand-name">Recording &amp; Acquisition</span></div>

			<div class="readouts">
				<div class="ro"><span>State</span><b :class="st.state">{{ st.state }}</b></div>
				<div class="ro"><span>Elapsed</span><b>{{ st.tSec.toFixed(2) }}s</b></div>
				<div class="ro"><span>RPM</span><b>{{ Math.round(st.rpm) }}</b></div>
				<div class="ro"><span>Samples</span><b>{{ st.nTotal.toLocaleString() }}</b></div>
				<div class="ro"><span>Fx</span><b class="fx">{{ st.peaks.Fx.toFixed(1) }}</b></div>
				<div class="ro"><span>Fy</span><b class="fy">{{ st.peaks.Fy.toFixed(1) }}</b></div>
				<div class="ro"><span>Fz</span><b class="fz">{{ st.peaks.Fz.toFixed(1) }}</b></div>
			</div>

			<button class="reset" title="Reset panel layout" @click="resetLayout"><span class="material-symbols-rounded">grid_view</span></button>
			<div class="conn" :class="{ ok: st.connected }">
				<span class="material-symbols-rounded">{{ st.connected ? 'sensors' : 'sensors_off' }}</span>
			</div>
		</header>

		<GridLayout v-model:layout="layout" :col-num="12" :row-height="30" :margin="[12, 12]"
			:is-draggable="true" :is-resizable="true" :use-css-transforms="true" :vertical-compact="true">
			<GridItem v-for="item in layout" :key="item.i" :x="item.x" :y="item.y" :w="item.w" :h="item.h" :i="item.i"
				drag-allow-from=".panel-handle" :min-w="2" :min-h="5">
				<PanelFrame :title="PANELS[item.i].title" :icon="PANELS[item.i].icon">
					<RecordingOptions v-if="item.i === 'options'" />
					<MetadataPanel v-else-if="item.i === 'metadata'" />
					<ForcePanel v-else-if="item.i === 'force'" />
					<FrmPanel v-else-if="item.i === 'frm'" />
					<PlotOptions v-else-if="item.i === 'plotopts'" />
				</PanelFrame>
			</GridItem>
		</GridLayout>
	</div>
</template>

<style scoped>
.rec-wrap { min-height: 100vh; background: radial-gradient(1200px 600px at 50% -10%, var(--bg-2), var(--bg)); padding-bottom: 24px; }
.topbar { position: sticky; top: 0; z-index: 20; display: flex; align-items: center; gap: 14px; padding: 12px 18px; border-bottom: 1px solid var(--border); background: rgba(11,16,32,0.82); backdrop-filter: blur(8px); }
.back, .reset { display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 34px; border-radius: 9px; background: var(--surface); border: 1px solid var(--border); color: var(--text); cursor: pointer; }
.back:hover, .reset:hover { background: var(--surface-2); }
.brand { display: flex; align-items: center; gap: 9px; }
.brand-name { font-weight: 600; white-space: nowrap; }
.rec-dot { width: 10px; height: 10px; border-radius: 50%; background: #64748b; }
.rec-dot.live { background: #ef4444; animation: pulse 1.4s infinite; }
@keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(239,68,68,0.5); } 70% { box-shadow: 0 0 0 8px rgba(239,68,68,0); } 100% { box-shadow: 0 0 0 0 rgba(239,68,68,0); } }
.readouts { display: flex; gap: 8px; margin: 0 auto; flex-wrap: wrap; }
.ro { display: flex; flex-direction: column; align-items: center; padding: 3px 10px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; }
.ro span { font-size: 9.5px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.04em; }
.ro b { font-size: 13px; font-variant-numeric: tabular-nums; }
.ro b.recording { color: #fbbf24; } .ro b.done { color: #4ade80; } .ro b.error { color: var(--danger); }
.ro b.fx { color: #f87171; } .ro b.fy { color: #4ade80; } .ro b.fz { color: #60a5fa; }
.conn { display: inline-flex; align-items: center; color: var(--text-dim); }
.conn.ok { color: #4ade80; }
.vgl-layout { margin: 8px 10px 0; }
:deep(.vgl-item--placeholder) { background: rgba(56,189,248,0.18); border-radius: 12px; }
:deep(.vgl-item__resizer) { z-index: 5; }
</style>
