<script setup lang="ts">
// Modular Recording workspace: a draggable/resizable grid of panels (Recording Options, Metadata,
// Force Plot w/ FFT, FRM Map, Plot Options), mirroring the Directus force-analysis feel. Layout is
// persisted to localStorage; panels share one workspace store via provide/inject.
import { onMounted, onBeforeUnmount, provide, ref, watch, computed } from 'vue';
import { GridLayout, GridItem } from 'grid-layout-plus';
import { createWorkspace, WORKSPACE } from './workspace';
import { startSync, syncStatus } from './directusSync';
import PanelFrame from './panels/PanelFrame.vue';
import RecordingOptions from './panels/RecordingOptions.vue';
import MetadataPanel from './panels/MetadataPanel.vue';
import ForcePanel from './panels/ForcePanel.vue';
import FrmPanel from './panels/FrmPanel.vue';
import RpmPanel from './panels/RpmPanel.vue';

const w = createWorkspace();
provide(WORKSPACE, w);
const st = w.st;

// Panel types. `single` types exist at most once; the rest can be added multiple times (e.g. two
// Force panels each isolating a different axis, or a second FRM). `w/h` seed a newly-added panel.
const PANEL_TYPES: Record<string, { title: string; icon: string; single?: boolean; w: number; h: number }> = {
	options: { title: 'Recording Options', icon: 'tune', single: true, w: 3, h: 12 },
	metadata: { title: 'Metadata', icon: 'description', single: true, w: 3, h: 14 },
	force: { title: 'Force Plot', icon: 'show_chart', w: 5, h: 11 },
	rpm: { title: 'RPM', icon: 'speed', w: 5, h: 7 },
	frm: { title: 'FRM Map', icon: 'fingerprint', w: 4, h: 19 },
};
type Inst = { i: string; type: string; x: number; y: number; w: number; h: number; mode?: 'time' | 'fft'; channels?: string[] };
const DEFAULT_LAYOUT: Inst[] = [
	{ i: 'options', type: 'options', x: 0, y: 0, w: 3, h: 12 },
	{ i: 'metadata', type: 'metadata', x: 0, y: 12, w: 3, h: 14 },
	{ i: 'force', type: 'force', x: 3, y: 0, w: 5, h: 12, mode: 'time', channels: ['Fx', 'Fy', 'Fz'] },
	{ i: 'rpm', type: 'rpm', x: 3, y: 12, w: 5, h: 7 },
	{ i: 'frm', type: 'frm', x: 8, y: 0, w: 4, h: 19 },
];
const LS_KEY = 'force-app.record.layout.v2';

function loadLayout(): Inst[] {
	try {
		const s = JSON.parse(localStorage.getItem(LS_KEY) || 'null');
		if (Array.isArray(s) && s.every((x) => x.type && PANEL_TYPES[x.type])) return s;
	} catch { /* fall through */ }
	return DEFAULT_LAYOUT.map((x) => ({ ...x }));
}
const layout = ref<Inst[]>(loadLayout());
let saveT: any = null;
watch(layout, (l) => { clearTimeout(saveT); saveT = setTimeout(() => localStorage.setItem(LS_KEY, JSON.stringify(l)), 400); }, { deep: true });
function resetLayout() { layout.value = DEFAULT_LAYOUT.map((x) => ({ ...x })); }

const addOpen = ref(false);
const hasType = (t: string) => layout.value.some((p) => p.type === t);
function panelTitle(p: Inst) {
	if (p.type === 'force' && p.channels && p.channels.join() !== 'Fx,Fy,Fz') return `Force · ${p.channels.join(' ')}`;
	return PANEL_TYPES[p.type].title;
}
function addPanel(type: string) {
	addOpen.value = false;
	const meta = PANEL_TYPES[type];
	if (meta.single && hasType(type)) return;
	const maxY = layout.value.reduce((m, p) => Math.max(m, p.y + p.h), 0);
	const inst: Inst = { i: `${type}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`, type, x: 0, y: maxY, w: meta.w, h: meta.h };
	if (type === 'force') { inst.mode = 'time'; inst.channels = ['Fx', 'Fy', 'Fz']; }
	layout.value = [...layout.value, inst];
}
function closePanel(i: string) { layout.value = layout.value.filter((p) => p.i !== i); }
const addable = computed(() => Object.entries(PANEL_TYPES).map(([type, m]) => ({ type, ...m, disabled: !!m.single && hasType(type) })));

// Load the finished cut on manual stop OR natural completion.
watch(() => st.state, (s) => { if (s === 'done' && !w.finishedCache.value) w.loadFinished(); });

onMounted(() => { w.client.connect(); startSync(); });
onBeforeUnmount(() => w.client.disconnect());
</script>

<template>
	<div class="rec-wrap" @click="addOpen = false">
		<!-- Global safety-alarm overlay (2e): prominent, blocks nothing but demands acknowledgement. -->
		<div v-if="w.alarms.tripped" class="alarm-overlay">
			<span class="material-symbols-rounded">warning</span>
			<div class="ao-text">
				<b>SAFETY ALARM</b>
				<span v-for="al in w.alarms.active" :key="al.key" class="ao-item">{{ al.label }} {{ al.value.toFixed(al.kind === 'rpm' ? 0 : 1) }}{{ al.kind === 'rpm' ? '' : ' N' }}</span>
			</div>
			<button class="ao-ack" @click="w.alarms.acknowledge()">Acknowledge</button>
		</div>

		<header class="topbar">
			<div class="brand"><span class="rec-dot" :class="{ live: w.isRecording.value }"></span><span class="brand-name">Recording &amp; Acquisition</span></div>

			<div class="readouts">
				<div class="ro"><span>State</span><b :class="st.state">{{ st.state }}</b></div>
				<div class="ro"><span>Elapsed</span><b>{{ st.tSec.toFixed(2) }}s</b></div>
				<div class="ro"><span>Cut</span><b :class="{ cut: st.cutStartSec !== null }">{{ st.cutStartSec !== null ? st.cutStartSec.toFixed(2) + 's' : '—' }}</b></div>
				<div class="ro"><span>RPM</span><b>{{ Math.round(st.rpm) }}</b></div>
				<div class="ro"><span>Samples</span><b>{{ st.nTotal.toLocaleString() }}</b></div>
				<div class="ro"><span>Fx</span><b class="fx">{{ st.peaks.Fx.toFixed(1) }}</b></div>
				<div class="ro"><span>Fy</span><b class="fy">{{ st.peaks.Fy.toFixed(1) }}</b></div>
				<div class="ro"><span>Fz</span><b class="fz">{{ st.peaks.Fz.toFixed(1) }}</b></div>
			</div>

			<div v-if="syncStatus.pending > 0 || syncStatus.lastError" class="syncchip" :class="syncStatus.pending > 0 ? 'warn' : 'err'"
				:title="syncStatus.lastError || `${syncStatus.pending} run record(s) queued offline`">
				<span class="material-symbols-rounded">{{ syncStatus.pending > 0 ? 'cloud_queue' : 'error' }}</span>
				<span v-if="syncStatus.pending > 0">{{ syncStatus.pending }}</span>
			</div>
			<div class="addwrap">
				<button class="reset" title="Add a panel" @click.stop="addOpen = !addOpen"><span class="material-symbols-rounded">add</span></button>
				<div v-if="addOpen" class="addmenu" @click.stop>
					<button v-for="a in addable" :key="a.type" :disabled="a.disabled" @click="addPanel(a.type)">
						<span class="material-symbols-rounded">{{ a.icon }}</span>{{ a.title }}<span v-if="a.disabled" class="added">added</span>
					</button>
				</div>
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
				<PanelFrame :title="panelTitle(item)" :icon="PANEL_TYPES[item.type].icon" closable @close="closePanel(item.i)">
					<RecordingOptions v-if="item.type === 'options'" />
					<MetadataPanel v-else-if="item.type === 'metadata'" />
					<ForcePanel v-else-if="item.type === 'force'" :inst="item" />
					<RpmPanel v-else-if="item.type === 'rpm'" />
					<FrmPanel v-else-if="item.type === 'frm'" />
				</PanelFrame>
			</GridItem>
		</GridLayout>
	</div>
</template>

<style scoped>
.rec-wrap { min-height: 100vh; background: radial-gradient(1200px 600px at 50% -10%, var(--bg-2), var(--bg)); padding-bottom: 24px; }
.alarm-overlay { position: fixed; top: 0; left: 0; right: 0; z-index: 100; display: flex; align-items: center; gap: 14px; padding: 12px 20px;
	color: #fff; background: #dc2626; box-shadow: 0 6px 24px rgba(220,38,38,0.5); animation: alarmpulse 0.9s ease-in-out infinite; }
@keyframes alarmpulse { 0%,100% { background: #dc2626; } 50% { background: #991b1b; } }
.alarm-overlay > .material-symbols-rounded { font-size: 28px; }
.ao-text { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.ao-text b { font-size: 15px; letter-spacing: 0.04em; }
.ao-item { font-size: 13px; font-variant-numeric: tabular-nums; background: rgba(0,0,0,0.2); padding: 2px 8px; border-radius: 6px; }
.ao-ack { margin-left: auto; padding: 8px 18px; font-size: 14px; font-weight: 700; color: #dc2626; background: #fff; border: none; border-radius: 8px; cursor: pointer; }
.topbar { position: sticky; top: 0; z-index: 20; display: flex; align-items: center; gap: 14px; padding: 12px 18px; border-bottom: 1px solid var(--border); background: rgba(11,16,32,0.82); backdrop-filter: blur(8px); }
.back, .reset { display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 34px; border-radius: 9px; background: var(--surface); border: 1px solid var(--border); color: var(--text); cursor: pointer; }
.back:hover, .reset:hover { background: var(--surface-2); }
.addwrap { position: relative; }
.addmenu { position: absolute; top: 40px; right: 0; z-index: 30; min-width: 190px; background: #0f1730; border: 1px solid var(--border); border-radius: 10px; padding: 5px; box-shadow: 0 14px 40px rgba(0,0,0,0.5); }
.addmenu button { display: flex; align-items: center; gap: 8px; width: 100%; padding: 8px 9px; font-size: 12.5px; color: var(--text); background: transparent; border: none; border-radius: 7px; cursor: pointer; text-align: left; }
.addmenu button:hover:not(:disabled) { background: #16203c; }
.addmenu button:disabled { opacity: 0.45; cursor: default; }
.addmenu button .material-symbols-rounded { font-size: 17px; color: var(--text-dim); }
.addmenu .added { margin-left: auto; font-size: 9.5px; color: var(--text-dim); }
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
.ro b.cut { color: #4ade80; }
.ro b.fx { color: #f87171; } .ro b.fy { color: #4ade80; } .ro b.fz { color: #60a5fa; }
.syncchip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 8px; border-radius: 8px; font-size: 12px; font-weight: 600; border: 1px solid var(--border); }
.syncchip .material-symbols-rounded { font-size: 16px; }
.syncchip.warn { color: #fbbf24; background: rgba(251,191,36,0.1); }
.syncchip.err { color: var(--danger); background: rgba(252,165,165,0.1); }
.conn { display: inline-flex; align-items: center; color: var(--text-dim); }
.conn.ok { color: #4ade80; }
.vgl-layout { margin: 8px 10px 0; }
:deep(.vgl-item--placeholder) { background: rgba(56,189,248,0.18); border-radius: 12px; }
:deep(.vgl-item__resizer) { z-index: 5; }
</style>
