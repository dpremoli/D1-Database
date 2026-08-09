<script setup lang="ts">
// Modular Recording workspace: a draggable/resizable grid of panels (Recording Options, Metadata,
// Force Plot w/ FFT, FRM Map, Plot Options), mirroring the Directus force-analysis feel. Layout is
// persisted to localStorage; panels share one workspace store via provide/inject.
import { onMounted, onBeforeUnmount, provide, reactive, ref, watch, computed } from 'vue';
import { GridLayout, GridItem } from 'grid-layout-plus';
import { createWorkspace, WORKSPACE } from './workspace';
import { startSync, syncStatus } from './directusSync';
import PanelFrame from './panels/PanelFrame.vue';
import RecordingOptions from './panels/RecordingOptions.vue';
import ForcePanel from './panels/ForcePanel.vue';
import FrmPanel from './panels/FrmPanel.vue';
import RpmPanel from './panels/RpmPanel.vue';
import OverviewPanel from './panels/OverviewPanel.vue';
import SaveCutDialog from './panels/SaveCutDialog.vue';


const w = createWorkspace();
provide(WORKSPACE, w);
const st = w.st;

// Panel types. `single` types exist at most once; the rest can be added multiple times (e.g. two
// Force panels each isolating a different axis, or a second FRM). `w/h` seed a newly-added panel.
const PANEL_TYPES: Record<string, { title: string; icon: string; single?: boolean; w: number; h: number }> = {
	options: { title: 'Recording & Metadata', icon: 'tune', single: true, w: 2, h: 28 },
	overview: { title: 'Overview', icon: 'monitoring', w: 4, h: 4 },
	force: { title: 'Force Plot', icon: 'show_chart', w: 6, h: 11 },
	rpm: { title: 'RPM', icon: 'speed', w: 6, h: 7 },
	frm: { title: 'FRM Map', icon: 'fingerprint', w: 4, h: 19 },

};
type Inst = { i: string; type: string; x: number; y: number; w: number; h: number; mode?: 'time' | 'fft' | 'psd' | 'spectrogram' | 'waterfall'; channels?: string[] };
const DEFAULT_LAYOUT: Inst[] = [
	{ i: 'options', type: 'options', x: 0, y: 0, w: 2, h: 28 },
	{ i: 'overview', type: 'overview', x: 2, y: 0, w: 6, h: 3 },
	{ i: 'force', type: 'force', x: 2, y: 3, w: 6, h: 12, mode: 'time', channels: ['Fx', 'Fy', 'Fz'] },
	{ i: 'fft', type: 'force', x: 2, y: 15, w: 6, h: 13, mode: 'fft', channels: ['Fx', 'Fy', 'Fz'] },
	{ i: 'frm', type: 'frm', x: 8, y: 0, w: 4, h: 20 },
	{ i: 'rpm', type: 'rpm', x: 8, y: 20, w: 4, h: 8 },
];
const LS_KEY = 'force-app.record.layout.v7';

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
const MODE_LABEL: Record<string, string> = { time: 'Force Plot', fft: 'FFT', psd: 'Power', spectrogram: 'Spectrogram', waterfall: 'Waterfall' };
function panelTitle(p: Inst) {
	if (p.type === 'force') {
		const mode = MODE_LABEL[p.mode || 'time'] || 'Force Plot';
		const ch = p.channels && p.channels.join() !== 'Fx,Fy,Fz' ? ` · ${p.channels.join(' ')}` : '';
		return mode + ch;
	}
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

watch(() => st.state, async (s, prev) => {
	// Covers auto-stop (self-terminating duration, disk-full, etc) where the frontend never called
	// w.stop() itself — the manual-stop path already opens this via workspace.ts's stop().
	if ((s === 'finalizing' || s === 'done' || s === 'error') && prev === 'recording') {
		w.saveOpen.value = true;
	}
	if (s === 'done' && prev !== 'done' && !w.finishedCache.value) {
		await w.loadFinished();
	}
});

// Periodic disk space check during recording (every 30s)
const diskInfo = reactive<{ free_gb: number; total_gb: number; used_pct: number; checking: boolean }>({ free_gb: -1, total_gb: 0, used_pct: 0, checking: false });
let diskTimer: ReturnType<typeof setInterval> | null = null;
async function checkDisk() {
	try {
		diskInfo.checking = true;
		const res = await fetch(`${w.client.baseUrl}/storage/config`);
		if (res.ok) {
			const data = await res.json();
			diskInfo.free_gb = data.free_gb ?? -1;
			diskInfo.total_gb = data.total_gb ?? 0;
			diskInfo.used_pct = data.used_pct ?? 0;
			w.alarms.evaluateDisk(diskInfo.free_gb);
		}
	} catch { /* backend unreachable */ } finally { diskInfo.checking = false; }
}
watch(() => st.state, (s) => {
	if (s === 'recording' && !diskTimer) {
		checkDisk();
		diskTimer = setInterval(checkDisk, 30_000);
	} else if (s !== 'recording' && diskTimer) {
		clearInterval(diskTimer);
		diskTimer = null;
	}
});

// ---- Live backup status ----
const backupStatus = reactive<{ enabled: boolean; state: string; progress: number; connected: boolean; error: string | null }>({
	enabled: false, state: '', progress: 0, connected: false, error: null,
});
async function checkBackup() {
	try {
		const res = await fetch(`${w.client.baseUrl}/backup/status`);
		if (res.ok) {
			const data = await res.json();
			backupStatus.enabled = data.enabled;
			if (data.active) {
				backupStatus.state = data.active.state;
				backupStatus.progress = data.active.progress_pct;
				backupStatus.connected = data.active.connected;
				backupStatus.error = data.active.error;
			} else {
				backupStatus.state = '';
				backupStatus.progress = 0;
			}
		}
	} catch { /* ignore */ }
}
let backupTimer: ReturnType<typeof setInterval> | null = null;
watch(() => st.state, (s) => {
	if (s === 'recording' && !backupTimer && backupStatus.enabled) {
		checkBackup();
		backupTimer = setInterval(checkBackup, 5_000);
	} else if (s !== 'recording' && backupTimer) {
		clearInterval(backupTimer);
		backupTimer = null;
		checkBackup();
	}
});

// ---- Recovery of incomplete recordings ----
interface IncompleteSession {
	id: string;
	started_iso: string;
	raw: { n_rows: number; duration_sec: number; rate: number; raw_size_mb: number };
	manifest?: { config?: { sample_name?: string } } | null;
}
const recoveryItems = ref<IncompleteSession[]>([]);
const recoveryBusy = ref<Record<string, boolean>>({});

async function checkRecovery() {
	try {
		const res = await fetch(`${w.client.baseUrl}/recovery/check`);
		if (res.ok) {
			const data = await res.json();
			recoveryItems.value = data.incomplete || [];
		}
	} catch { /* backend unreachable */ }
}

async function recoverSession(id: string) {
	recoveryBusy.value[id] = true;
	try {
		const res = await fetch(`${w.client.baseUrl}/recovery/recover/${id}`, { method: 'POST' });
		if (!res.ok) throw new Error(`HTTP ${res.status}`);
		recoveryItems.value = recoveryItems.value.filter((s) => s.id !== id);
	} catch (e: any) {
		alert(`Recovery failed: ${e?.message || e}`);
	} finally {
		delete recoveryBusy.value[id];
	}
}

async function discardSession(id: string) {
	if (!confirm(`Discard incomplete recording ${id}? This cannot be undone.`)) return;
	recoveryBusy.value[id] = true;
	try {
		const res = await fetch(`${w.client.baseUrl}/recovery/discard/${id}`, { method: 'POST' });
		if (!res.ok) throw new Error(`HTTP ${res.status}`);
		recoveryItems.value = recoveryItems.value.filter((s) => s.id !== id);
	} catch (e: any) {
		alert(`Discard failed: ${e?.message || e}`);
	} finally {
		delete recoveryBusy.value[id];
	}
}

onMounted(() => { w.client.connect(); startSync(); checkDisk(); checkRecovery(); checkBackup(); });
onBeforeUnmount(() => { w.client.disconnect(); if (diskTimer) clearInterval(diskTimer); if (backupTimer) clearInterval(backupTimer); });
</script>

<template>
	<div class="rec-wrap" @click="addOpen = false">
		<!-- Disk-full protection: the backend watches free space during a recording independently of
			 this page's own polling, and reports what (if anything) it had to do about it. -->
		<div v-if="st.diskAction" class="disk-action-banner" :class="st.diskAction.action">
			<span class="material-symbols-rounded">{{ st.diskAction.action === 'forced_stop' ? 'dangerous' : st.diskAction.action === 'backup_started' ? 'cloud_upload' : 'warning' }}</span>
			<span v-if="st.diskAction.action === 'backup_started'">Disk space is low ({{ st.diskAction.freeGb.toFixed(1) }} GB free) — remote backup was switched on automatically to protect this recording.</span>
			<span v-else-if="st.diskAction.action === 'forced_stop'">Recording was stopped automatically — disk space ran critically low ({{ st.diskAction.freeGb.toFixed(1) }} GB free). The data captured so far is safe.</span>
			<span v-else>Disk space is low ({{ st.diskAction.freeGb.toFixed(1) }} GB free) and no remote backup is configured — free up space or configure a backup server soon.</span>
			<button class="disk-action-ack" @click="st.diskAction = null">Dismiss</button>
		</div>

		<!-- Global safety-alarm overlay (2e): prominent, blocks nothing but demands acknowledgement. -->
		<div v-if="w.alarms.tripped" class="alarm-overlay">
			<span class="material-symbols-rounded">warning</span>
			<div class="ao-text">
				<b>SAFETY ALARM</b>
				<span v-for="al in w.alarms.active" :key="al.key" class="ao-item">{{ al.label }} {{ al.value.toFixed(al.kind === 'rpm' ? 0 : 1) }}{{ al.kind === 'rpm' ? '' : al.kind === 'disk' ? ' GB' : ' N' }}</span>
			</div>
			<button class="ao-ack" @click="w.alarms.acknowledge()">Acknowledge</button>
		</div>

		<!-- Recovery banner for incomplete recordings found on startup -->
		<div v-if="recoveryItems.length" class="recovery-banner">
			<div class="rb-head">
				<span class="material-symbols-rounded">restore</span>
				<b>{{ recoveryItems.length }} incomplete recording{{ recoveryItems.length > 1 ? 's' : '' }} found</b>
				<span class="rb-hint">These recordings were interrupted by a crash or power failure. You can recover the data or discard them.</span>
			</div>
			<div v-for="s in recoveryItems" :key="s.id" class="rb-item">
				<div class="rb-info">
					<span class="rb-id">{{ s.id }}</span>
					<span class="rb-detail">{{ s.raw.duration_sec.toFixed(1) }}s · {{ s.raw.n_rows.toLocaleString() }} samples · {{ s.raw.raw_size_mb }} MB</span>
					<span v-if="s.manifest?.config?.sample_name" class="rb-detail">{{ s.manifest.config.sample_name }}</span>
				</div>
				<button class="rb-btn recover" :disabled="!!recoveryBusy[s.id]" @click="recoverSession(s.id)">
					<span class="material-symbols-rounded">healing</span>{{ recoveryBusy[s.id] ? 'Recovering…' : 'Recover' }}
				</button>
				<button class="rb-btn discard" :disabled="!!recoveryBusy[s.id]" @click="discardSession(s.id)">
					<span class="material-symbols-rounded">delete</span>Discard
				</button>
			</div>
		</div>

		<header class="topbar">
			<span class="rec-dot" :class="{ live: w.isRecording.value }" :title="w.st.state"></span>

			<div class="spacer"></div>
			<div v-if="syncStatus.pending > 0 || syncStatus.lastError" class="syncchip" :class="syncStatus.pending > 0 ? 'warn' : 'err'"
				:title="syncStatus.lastError || `${syncStatus.pending} run record(s) queued offline`">
				<span class="material-symbols-rounded">{{ syncStatus.pending > 0 ? 'cloud_queue' : 'error' }}</span>
				<span v-if="syncStatus.pending > 0">{{ syncStatus.pending }}</span>
			</div>
			<div v-if="diskInfo.free_gb >= 0" class="diskchip" :class="{ warn: diskInfo.free_gb < 10, crit: diskInfo.free_gb < 5 }"
				:title="`${diskInfo.free_gb.toFixed(1)} GB free of ${diskInfo.total_gb.toFixed(0)} GB`">
				<span class="material-symbols-rounded">hard_drive</span>
				<span>{{ diskInfo.free_gb < 100 ? diskInfo.free_gb.toFixed(1) : Math.round(diskInfo.free_gb) }} GB</span>
			</div>
			<div v-if="backupStatus.enabled" class="backupchip"
				:class="{ streaming: backupStatus.state === 'streaming', paused: backupStatus.state === 'paused', done: backupStatus.state === 'done', err: backupStatus.state === 'error' }"
				:title="backupStatus.error || `Backup ${backupStatus.state || 'idle'} · ${backupStatus.progress.toFixed(0)}%`">
				<span class="material-symbols-rounded">{{ backupStatus.connected ? 'cloud_done' : 'cloud_off' }}</span>
				<span v-if="backupStatus.state === 'streaming'">{{ backupStatus.progress.toFixed(0) }}%</span>
				<span v-else-if="backupStatus.state === 'paused'">paused</span>
				<span v-else-if="backupStatus.state">{{ backupStatus.state }}</span>
			</div>
			<div class="conn" :class="{ ok: st.connected }">
				<span class="material-symbols-rounded">{{ st.connected ? 'sensors' : 'sensors_off' }}</span>
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
		</header>

		<GridLayout v-model:layout="layout" :col-num="12" :row-height="30" :margin="[12, 12]"
			:is-draggable="true" :is-resizable="true" :use-css-transforms="true" :vertical-compact="true">
			<GridItem v-for="item in layout" :key="item.i" :x="item.x" :y="item.y" :w="item.w" :h="item.h" :i="item.i"
				drag-allow-from=".panel-handle" :min-w="2" :min-h="3">
				<PanelFrame :title="panelTitle(item)" :icon="PANEL_TYPES[item.type].icon" closable @close="closePanel(item.i)">
					<RecordingOptions v-if="item.type === 'options'" />
					<OverviewPanel v-else-if="item.type === 'overview'" />
					<ForcePanel v-else-if="item.type === 'force'" :inst="item" />
					<RpmPanel v-else-if="item.type === 'rpm'" />
					<FrmPanel v-else-if="item.type === 'frm'" />
				</PanelFrame>
			</GridItem>
		</GridLayout>

		<SaveCutDialog v-if="w.saveOpen.value" />
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
.disk-action-banner { position: sticky; top: 0; z-index: 90; display: flex; align-items: center; gap: 12px; padding: 10px 18px; font-size: 13px; color: #fff; }
.disk-action-banner.backup_started { background: #2563eb; }
.disk-action-banner.backup_unavailable { background: #b45309; }
.disk-action-banner.forced_stop { background: #dc2626; }
.disk-action-banner .material-symbols-rounded { font-size: 20px; }
.disk-action-ack { margin-left: auto; padding: 6px 14px; font-size: 12px; font-weight: 700; color: inherit; background: rgba(255,255,255,0.18); border: none; border-radius: 7px; cursor: pointer; }
.disk-action-ack:hover { background: rgba(255,255,255,0.28); }
.topbar { position: sticky; top: 0; z-index: 20; display: flex; align-items: center; gap: 8px; padding: 6px 14px; border-bottom: 1px solid var(--border); background: color-mix(in srgb, var(--bg) 82%, transparent); backdrop-filter: blur(8px); }
.back, .reset { display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: 8px; background: var(--surface); border: 1px solid var(--border); color: var(--text); cursor: pointer; }
.back:hover, .reset:hover { background: var(--surface-2); }
.reset .material-symbols-rounded { font-size: 17px; }
.addwrap { position: relative; }
.addmenu { position: absolute; top: 32px; right: 0; z-index: 30; min-width: 190px; background: var(--bg-2); border: 1px solid var(--border); border-radius: 10px; padding: 5px; box-shadow: 0 14px 40px rgba(0,0,0,0.3); }
.addmenu button { display: flex; align-items: center; gap: 8px; width: 100%; padding: 8px 9px; font-size: 12.5px; color: var(--text); background: transparent; border: none; border-radius: 7px; cursor: pointer; text-align: left; }
.addmenu button:hover:not(:disabled) { background: var(--surface-2); }
.addmenu button:disabled { opacity: 0.45; cursor: default; }
.addmenu button .material-symbols-rounded { font-size: 17px; color: var(--text-dim); }
.addmenu .added { margin-left: auto; font-size: 9.5px; color: var(--text-dim); }
.rec-dot { width: 9px; height: 9px; border-radius: 50%; background: #64748b; flex-shrink: 0; }
.rec-dot.live { background: #ef4444; animation: pulse 1.4s infinite; }
@keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(239,68,68,0.5); } 70% { box-shadow: 0 0 0 8px rgba(239,68,68,0); } 100% { box-shadow: 0 0 0 0 rgba(239,68,68,0); } }
.spacer { flex: 1; }
.syncchip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 8px; border-radius: 8px; font-size: 12px; font-weight: 600; border: 1px solid var(--border); }
.syncchip .material-symbols-rounded { font-size: 16px; }
.syncchip.warn { color: #fbbf24; background: rgba(251,191,36,0.1); }
.syncchip.err { color: var(--danger); background: rgba(252,165,165,0.1); }
.diskchip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 8px; border-radius: 8px; font-size: 11px; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--text-dim); border: 1px solid var(--border); }
.diskchip .material-symbols-rounded { font-size: 15px; }
.diskchip.warn { color: #fbbf24; background: rgba(251,191,36,0.1); border-color: rgba(251,191,36,0.3); }
.diskchip.crit { color: #ef4444; background: rgba(239,68,68,0.1); border-color: rgba(239,68,68,0.3); animation: alarmpulse 0.9s ease-in-out infinite; }
.backupchip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 8px; border-radius: 8px; font-size: 11px; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--text-dim); border: 1px solid var(--border); }
.backupchip .material-symbols-rounded { font-size: 15px; }
.backupchip.streaming { color: #22c55e; background: rgba(34,197,94,0.1); border-color: rgba(34,197,94,0.3); }
.backupchip.paused { color: #fbbf24; background: rgba(251,191,36,0.1); border-color: rgba(251,191,36,0.3); }
.backupchip.done { color: #4ade80; }
.backupchip.err { color: var(--danger); background: rgba(239,68,68,0.1); border-color: rgba(239,68,68,0.3); }
.conn { display: inline-flex; align-items: center; color: var(--text-dim); }
.conn.ok { color: #4ade80; }
/* Recovery banner */
.recovery-banner { background: color-mix(in srgb, var(--bg-2) 95%, #fbbf24 5%); border-bottom: 1px solid rgba(251,191,36,0.3); padding: 14px 18px; }
.rb-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.rb-head > .material-symbols-rounded { font-size: 22px; color: #fbbf24; }
.rb-head b { font-size: 14px; color: var(--text); }
.rb-hint { font-size: 12px; color: var(--text-dim); }
.rb-item { display: flex; align-items: center; gap: 10px; padding: 8px 10px; background: var(--surface); border: 1px solid var(--border); border-radius: 9px; margin-bottom: 6px; }
.rb-info { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.rb-id { font-size: 12px; font-weight: 600; font-family: var(--mono); color: var(--text); }
.rb-detail { font-size: 11px; color: var(--text-dim); font-variant-numeric: tabular-nums; }
.rb-btn { display: inline-flex; align-items: center; gap: 5px; padding: 6px 12px; font-size: 12px; font-weight: 600; border: none; border-radius: 7px; cursor: pointer; }
.rb-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.rb-btn .material-symbols-rounded { font-size: 15px; }
.rb-btn.recover { color: #fff; background: #22c55e; }
.rb-btn.recover:hover:not(:disabled) { background: #16a34a; }
.rb-btn.discard { color: var(--text-dim); background: var(--surface-2); }
.rb-btn.discard:hover:not(:disabled) { color: var(--danger); background: rgba(239,68,68,0.1); }
.vgl-layout { margin: 8px 10px 0; }
:deep(.vgl-item--placeholder) { background: rgba(56,189,248,0.18); border-radius: 12px; }
:deep(.vgl-item__resizer) { z-index: 5; }
</style>
