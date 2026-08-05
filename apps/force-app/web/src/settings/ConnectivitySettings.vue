<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { getConfig } from '../config';

interface ProbeResult { label: string; url?: string; ok: boolean; status?: number; error?: string; }
interface DiskInfo { path?: string; free_gb: number; total_gb: number; used_pct: number; captures_root?: string; }

const probes = ref<ProbeResult[]>([]);
const disk = ref<DiskInfo | null>(null);
const loading = ref(false);
const lastChecked = ref('');

async function runCheck() {
	loading.value = true;
	try {
		const base = getConfig().recorderUrl;
		const res = await fetch(`${base}/health/check`);
		if (!res.ok) throw new Error(`HTTP ${res.status}`);
		const data = await res.json();
		probes.value = data.probes || [];
		disk.value = data.disk || null;
		lastChecked.value = new Date().toLocaleTimeString();
	} catch {
		probes.value = [{ label: 'Recorder backend', ok: false, error: 'unreachable' }];
		disk.value = null;
		lastChecked.value = new Date().toLocaleTimeString();
	} finally {
		loading.value = false;
	}
}

onMounted(() => runCheck());
</script>

<template>
	<div class="connectivity">
		<h2>Connection self-check</h2>
		<p class="lead">Tests connectivity from the recording backend to Internet, database, and equipment. Run this to diagnose upload or hardware communication issues.</p>

		<div class="actions">
			<button class="btn ghost" :disabled="loading" @click="runCheck">
				<span class="material-symbols-rounded">{{ loading ? 'hourglass_top' : 'refresh' }}</span>
				{{ loading ? 'Checking…' : 'Run check' }}
			</button>
			<span v-if="lastChecked" class="last">Last checked: {{ lastChecked }}</span>
		</div>

		<div v-if="probes.length" class="results">
			<div v-for="p in probes" :key="p.label" class="probe" :class="{ ok: p.ok, fail: !p.ok }">
				<span class="material-symbols-rounded icon">{{ p.ok ? 'check_circle' : 'cancel' }}</span>
				<div class="probe-body">
					<span class="probe-label">{{ p.label }}</span>
					<span v-if="p.url" class="probe-url">{{ p.url }}</span>
				</div>
				<span class="probe-status">
					<template v-if="p.ok">OK</template>
					<template v-else-if="p.error">{{ p.error }}</template>
					<template v-else>HTTP {{ p.status }}</template>
				</span>
			</div>
		</div>

		<div v-if="disk" class="disk-section">
			<h3>Recording storage</h3>
			<div class="disk-info">
				<div class="disk-stat"><span>Location</span><b class="mono">{{ disk.captures_root || disk.path }}</b></div>
				<div class="disk-row">
					<div class="disk-stat"><span>Free</span><b :class="{ warn: disk.free_gb < 10, crit: disk.free_gb < 5 }">{{ disk.free_gb.toFixed(1) }} GB</b></div>
					<div class="disk-stat"><span>Total</span><b>{{ disk.total_gb.toFixed(0) }} GB</b></div>
					<div class="disk-stat"><span>Used</span><b>{{ disk.used_pct.toFixed(1) }}%</b></div>
				</div>
				<div class="disk-bar-wrap">
					<div class="disk-bar" :class="{ warn: disk.used_pct > 85, crit: disk.used_pct > 95 }" :style="{ width: disk.used_pct + '%' }"></div>
				</div>
			</div>
			<p v-if="disk.free_gb < 5" class="alert">
				<span class="material-symbols-rounded">warning</span>
				Critically low disk space. Recordings may fail or be truncated.
			</p>
			<p v-else-if="disk.free_gb < 10" class="alert warn-alert">
				<span class="material-symbols-rounded">info</span>
				Disk space is running low. Consider changing storage location in General settings.
			</p>
		</div>
	</div>
</template>

<style scoped>
.connectivity { max-width: 620px; }
h2 { margin: 0 0 4px; font-size: 16px; }
h3 { margin: 24px 0 8px; font-size: 14px; }
.lead { margin: 0 0 18px; font-size: 13px; color: var(--text-dim); line-height: 1.5; }
.actions { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.btn { display: inline-flex; align-items: center; gap: 6px; padding: 9px 16px; font-size: 13px; font-weight: 600; border: none; border-radius: 8px; cursor: pointer; }
.btn.ghost { background: var(--surface); color: var(--text); border: 1px solid var(--border); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn .material-symbols-rounded { font-size: 17px; }
.last { font-size: 11.5px; color: var(--text-dim); }

.results { display: flex; flex-direction: column; gap: 6px; }
.probe { display: flex; align-items: center; gap: 10px; padding: 10px 12px; background: var(--surface); border-radius: 9px; border: 1px solid var(--border); }
.probe .icon { font-size: 20px; }
.probe.ok .icon { color: #4ade80; }
.probe.fail .icon { color: var(--danger); }
.probe-body { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.probe-label { font-size: 13.5px; font-weight: 600; color: var(--text); }
.probe-url { font-size: 11px; color: var(--text-dim); font-family: var(--mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.probe-status { font-size: 12px; font-weight: 600; }
.probe.ok .probe-status { color: #4ade80; }
.probe.fail .probe-status { color: var(--danger); }

.disk-section { margin-top: 8px; }
.disk-info { padding: 12px; background: var(--surface); border-radius: 9px; border: 1px solid var(--border); }
.disk-stat { display: flex; flex-direction: column; }
.disk-stat span { font-size: 10px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.04em; }
.disk-stat b { font-size: 13px; font-variant-numeric: tabular-nums; }
.disk-stat b.mono { font-family: var(--mono); font-size: 11.5px; word-break: break-all; }
.disk-stat b.warn { color: #fbbf24; }
.disk-stat b.crit { color: #ef4444; }
.disk-row { display: flex; gap: 20px; margin-top: 8px; }
.disk-bar-wrap { width: 100%; height: 6px; background: var(--surface-2); border-radius: 3px; overflow: hidden; margin-top: 10px; }
.disk-bar { height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.3s; }
.disk-bar.warn { background: #fbbf24; }
.disk-bar.crit { background: #ef4444; }

.alert { display: flex; align-items: center; gap: 6px; margin-top: 10px; padding: 8px 12px; border-radius: 8px; font-size: 12.5px; font-weight: 600; color: #ef4444; background: rgba(239,68,68,0.08); }
.alert .material-symbols-rounded { font-size: 18px; }
.alert.warn-alert { color: #fbbf24; background: rgba(251,191,36,0.08); }
</style>
