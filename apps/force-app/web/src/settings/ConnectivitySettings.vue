<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { getConfig, getConfigDefaults, setConfigOverride, resetConfigOverride } from '../config';

interface Finding {
	service: string;
	status: 'ok' | 'fail' | 'warn' | 'info';
	message: string;
	diagnosis?: string;
	fix?: string;
	fix_command?: string;
	fixable?: string;
}
interface DiskInfo { path?: string; free_gb: number; total_gb: number; used_pct: number; captures_root?: string; }

const findings = ref<Finding[]>([]);
const disk = ref<DiskInfo | null>(null);
const loading = ref(false);
const lastChecked = ref('');
const recorderDown = ref(false);
const fixingId = ref('');

async function runDoctor() {
	loading.value = true;
	findings.value = [];
	disk.value = null;
	recorderDown.value = false;

	const cfg = getConfig();

	// First check if the recorder backend itself is reachable
	try {
		const r = await fetch(`${cfg.recorderUrl}/health`, { signal: AbortSignal.timeout(5000) });
		if (!r.ok) throw new Error();
	} catch {
		// Recorder is down — run frontend-only diagnostics
		recorderDown.value = true;
		const list: Finding[] = [];

		// Parse the recorder URL to diagnose why it's unreachable
		try {
			const u = new URL(cfg.recorderUrl);
			const host = u.hostname;
			const port = u.port || (u.protocol === 'https:' ? '443' : '80');
			const isLocal = host === 'localhost' || host === '127.0.0.1';
			const backendPath = window.location.hostname === 'localhost'
				? 'C:\\Users\\WS-X180-PC\\Documents\\GitHub\\D1-Database\\apps\\force-app\\backend'
				: 'apps\\force-app\\backend';
			list.push({
				service: 'Recorder backend',
				status: 'fail',
				message: `Cannot reach ${cfg.recorderUrl}`,
				diagnosis: isLocal
					? `The recorder backend is not running on this machine (port ${port}). It needs to be started as a background process before recording.`
					: `Cannot connect to ${host}:${port}. Check that the recorder backend is running on that host and the URL is correct in Settings > General.`,
				fix: isLocal
					? 'Start the backend by running this command in a terminal:'
					: `Verify the Recorder URL in Settings > General, or start the backend on ${host}.`,
				fix_command: isLocal
					? `cd "${backendPath}"; python -m uvicorn app.main:app --host 0.0.0.0 --port ${port}`
					: undefined,
			});
		} catch {
			list.push({
				service: 'Recorder backend',
				status: 'fail',
				message: 'Invalid recorder URL',
				diagnosis: `The configured recorder URL "${cfg.recorderUrl}" is not a valid URL.`,
				fix: 'Fix the Recorder URL in Settings > General (e.g. http://localhost:8200).',
			});
		}

		// Test other endpoints from the browser
		const endpoints: { label: string; url: string }[] = [
			{ label: 'Directus / database', url: `${cfg.directusUrl}/server/ping` },
			{ label: 'Filter service', url: `${cfg.filterUrl}/health` },
			{ label: 'Octree server', url: `${cfg.octreeUrl}/` },
		];
		await Promise.all(endpoints.map(async (ep) => {
			try {
				const r = await fetch(ep.url, { signal: AbortSignal.timeout(5000) });
				const isOctree = ep.label.toLowerCase().includes('octree');
				const ok = r.ok || (isOctree && r.status === 404);
				list.push({ service: ep.label, status: ok ? 'ok' : 'warn', message: ok ? 'Reachable' : `HTTP ${r.status}` });
			} catch {
				list.push({ service: ep.label, status: 'fail', message: 'Unreachable', diagnosis: `Cannot reach ${ep.url} from this browser.` });
			}
		}));

		findings.value = list;
		lastChecked.value = new Date().toLocaleTimeString();
		loading.value = false;
		return;
	}

	// Recorder is up — use the doctor endpoint for deep diagnostics
	try {
		const res = await fetch(`${cfg.recorderUrl}/health/doctor`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				directus_url: cfg.directusUrl,
				filter_url: cfg.filterUrl,
				octree_url: cfg.octreeUrl,
			}),
		});
		if (!res.ok) throw new Error(`HTTP ${res.status}`);
		const data = await res.json();
		findings.value = data.findings || [];
		disk.value = data.disk || null;
	} catch (e: any) {
		findings.value = [{ service: 'Doctor', status: 'fail', message: `Doctor endpoint failed: ${e?.message}` }];
	}

	lastChecked.value = new Date().toLocaleTimeString();
	loading.value = false;
}

async function applyFix(f: Finding) {
	if (!f.fixable) return;
	fixingId.value = f.service;
	try {
		const base = getConfig().recorderUrl;
		if (f.fixable === 'purge_incomplete') {
			const incomplete = await fetch(`${base}/recovery/check`).then(r => r.json());
			for (const s of incomplete.incomplete || []) {
				await fetch(`${base}/recovery/discard/${s.id}`, { method: 'POST' });
			}
			await runDoctor();
		}
	} catch { /* ignore */ } finally {
		fixingId.value = '';
	}
}

const copied = ref('');
function copyCommand(cmd: string, service: string) {
	navigator.clipboard.writeText(cmd);
	copied.value = service;
	setTimeout(() => { if (copied.value === service) copied.value = ''; }, 2000);
}

// ---- Service endpoints editor ----
const epFields: { key: 'directusUrl' | 'filterUrl' | 'octreeUrl' | 'recorderUrl'; label: string; hint: string }[] = [
	{ key: 'recorderUrl', label: 'Recorder URL', hint: 'Local recording/acquisition backend + Lab Amp proxy.' },
	{ key: 'directusUrl', label: 'Directus URL', hint: 'REST base for items, assets and auth.' },
	{ key: 'filterUrl', label: 'Filter service URL', hint: 'Signal-filter sidecar (/run, /fft).' },
	{ key: 'octreeUrl', label: 'Octree server URL', hint: 'Potree LOD octree static host.' },
];
const epForm = reactive({ ...getConfig() });
const epSaved = ref(false);
function saveEndpoints() {
	setConfigOverride({ ...epForm });
	epSaved.value = true;
	setTimeout(() => (epSaved.value = false), 2000);
}
function resetEndpoints() {
	resetConfigOverride();
	Object.assign(epForm, getConfigDefaults());
}

const statusIcon: Record<string, string> = { ok: 'check_circle', fail: 'cancel', warn: 'warning', info: 'info' };
const statusColor: Record<string, string> = { ok: '#4ade80', fail: 'var(--danger)', warn: '#fbbf24', info: 'var(--accent)' };

onMounted(() => runDoctor());
</script>

<template>
	<div class="connectivity">
		<h2>Connectivity Doctor</h2>
		<p class="lead">Diagnoses all connections, hardware, and system health. Identifies problems and suggests fixes.</p>

		<div class="actions">
			<button class="btn ghost" :disabled="loading" @click="runDoctor">
				<span class="material-symbols-rounded">{{ loading ? 'hourglass_top' : 'stethoscope' }}</span>
				{{ loading ? 'Diagnosing…' : 'Run doctor' }}
			</button>
			<span v-if="lastChecked" class="last">{{ lastChecked }}</span>
		</div>

		<div v-if="recorderDown" class="recorder-alert">
			<span class="material-symbols-rounded">power_off</span>
			<div>
				<b>Recorder backend is offline</b>
				<p>Some diagnostics are limited because the backend is not reachable. Fix the recorder connection first.</p>
			</div>
		</div>

		<div v-if="findings.length" class="results">
			<div v-for="f in findings" :key="f.service" class="finding" :class="f.status">
				<span class="material-symbols-rounded icon" :style="{ color: statusColor[f.status] }">{{ statusIcon[f.status] }}</span>
				<div class="finding-body">
					<div class="finding-head">
						<span class="finding-service">{{ f.service }}</span>
						<span class="finding-msg">{{ f.message }}</span>
					</div>
					<div v-if="f.diagnosis" class="finding-diagnosis">
						<span class="material-symbols-rounded" style="font-size:13px;flex-shrink:0">search</span>
						{{ f.diagnosis }}
					</div>
					<div v-if="f.fix" class="finding-fix">
						<span class="material-symbols-rounded" style="font-size:13px;flex-shrink:0">build</span>
						<span class="fix-text">{{ f.fix }}</span>
						<button v-if="f.fixable" class="fix-btn" :disabled="fixingId === f.service" @click="applyFix(f)">
							{{ fixingId === f.service ? 'Fixing…' : 'Fix now' }}
						</button>
					</div>
					<div v-if="f.fix_command" class="cmd-block">
						<code>{{ f.fix_command }}</code>
						<button class="copy-btn" @click="copyCommand(f.fix_command!, f.service)">
							<span class="material-symbols-rounded">{{ copied === f.service ? 'check' : 'content_copy' }}</span>
							{{ copied === f.service ? 'Copied' : 'Copy' }}
						</button>
					</div>
				</div>
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
		</div>

		<div v-if="!loading && findings.length && findings.every(f => f.status === 'ok' || f.status === 'info')" class="all-good">
			<span class="material-symbols-rounded">verified</span>
			All systems healthy
		</div>

		<h2 class="mt">Service endpoints</h2>
		<p class="lead">Where the app connects to Directus and local services. Changes are saved to this browser and take effect immediately.</p>
		<label v-for="f in epFields" :key="f.key" class="field">
			<span class="lbl">{{ f.label }}</span>
			<input v-model="epForm[f.key]" spellcheck="false" />
			<span class="ep-hint">{{ f.hint }}</span>
		</label>
		<div class="actions">
			<button class="btn save" @click="saveEndpoints">{{ epSaved ? 'Saved ✓' : 'Save' }}</button>
			<button class="btn ghost" @click="resetEndpoints">Reset to defaults</button>
			<button class="btn ghost" @click="runDoctor">
				<span class="material-symbols-rounded" style="font-size:15px">stethoscope</span>
				Re-check
			</button>
		</div>
	</div>
</template>

<style scoped>
.connectivity { max-width: 660px; }
h2 { margin: 0 0 4px; font-size: 16px; }
h3 { margin: 24px 0 8px; font-size: 14px; }
.mt { margin-top: 32px; }

/* Endpoint editor */
.field { display: block; margin-bottom: 14px; }
.lbl { display: block; font-size: 12.5px; font-weight: 600; color: var(--text); margin-bottom: 5px; }
.field input { display: block; width: 100%; padding: 9px 11px; font-size: 13px; font-family: var(--mono); color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: 8px; outline: none; box-sizing: border-box; }
.field input:focus { border-color: var(--accent); }
.ep-hint { display: block; font-size: 11.5px; color: var(--text-dim); margin-top: 3px; }
.btn.save { background: var(--accent); color: var(--accent-ink); }
.lead { margin: 0 0 18px; font-size: 13px; color: var(--text-dim); line-height: 1.5; }
.actions { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.btn { display: inline-flex; align-items: center; gap: 6px; padding: 9px 16px; font-size: 13px; font-weight: 600; border: none; border-radius: 8px; cursor: pointer; }
.btn.ghost { background: var(--surface); color: var(--text); border: 1px solid var(--border); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn .material-symbols-rounded { font-size: 17px; }
.last { font-size: 11.5px; color: var(--text-dim); }

.recorder-alert { display: flex; align-items: flex-start; gap: 10px; padding: 12px 14px; margin-bottom: 14px; background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.25); border-radius: 10px; }
.recorder-alert .material-symbols-rounded { font-size: 22px; color: var(--danger); margin-top: 1px; }
.recorder-alert b { font-size: 13px; color: var(--text); }
.recorder-alert p { margin: 2px 0 0; font-size: 12px; color: var(--text-dim); }

.results { display: flex; flex-direction: column; gap: 6px; }
.finding { display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px; background: var(--surface); border-radius: 9px; border: 1px solid var(--border); }
.finding .icon { font-size: 20px; margin-top: 1px; flex-shrink: 0; }
.finding-body { flex: 1; min-width: 0; }
.finding-head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.finding-service { font-size: 13px; font-weight: 700; color: var(--text); }
.finding-msg { font-size: 12px; color: var(--text-dim); }
.finding-diagnosis { display: flex; align-items: flex-start; gap: 5px; margin-top: 5px; font-size: 11.5px; color: var(--text-dim); line-height: 1.45; }
.finding-fix { display: flex; align-items: flex-start; gap: 5px; margin-top: 4px; font-size: 11.5px; color: var(--accent); line-height: 1.45; }
/* Only the text grows — a bare `span` selector also caught the wrench icon, so the two split the
   row 50/50 and every fix line started half-way across the card, away from its icon. */
.finding-fix .fix-text { flex: 1; }

.fix-btn { padding: 3px 10px; font-size: 11px; font-weight: 700; color: #fff; background: #22c55e; border: none; border-radius: 5px; cursor: pointer; white-space: nowrap; flex-shrink: 0; }
.fix-btn:hover:not(:disabled) { background: #16a34a; }
.fix-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.cmd-block { display: flex; align-items: center; gap: 8px; margin-top: 6px; padding: 8px 10px; background: var(--bg); border: 1px solid var(--border); border-radius: 7px; }
.cmd-block code { flex: 1; font-family: var(--mono); font-size: 11.5px; color: var(--text); word-break: break-all; user-select: all; }
.copy-btn { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; font-size: 11px; font-weight: 700; color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: 5px; cursor: pointer; white-space: nowrap; flex-shrink: 0; }
.copy-btn .material-symbols-rounded { font-size: 14px; }
.copy-btn:hover { background: var(--surface-2); }

.all-good { display: flex; align-items: center; gap: 8px; margin-top: 16px; padding: 12px 16px; background: rgba(74,222,128,0.08); border: 1px solid rgba(74,222,128,0.2); border-radius: 10px; font-size: 14px; font-weight: 700; color: #4ade80; }
.all-good .material-symbols-rounded { font-size: 22px; }

.disk-section { margin-top: 16px; }
.disk-info { padding: 12px; background: var(--surface); border-radius: 9px; border: 1px solid var(--border); }
.disk-stat { display: flex; flex-direction: column; }
.disk-stat span { font-size: 10px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.04em; }
.disk-stat b { font-size: 13px; font-variant-numeric: tabular-nums; }
.disk-stat b.mono { font-family: var(--mono); font-size: 11.5px; word-break: break-all; }
.disk-stat b.warn { color: #fbbf24; }
.disk-stat b.crit { color: #ef4444; }
.disk-row { display: flex; gap: 20px; margin-top: 8px; flex-wrap: wrap; }
.disk-bar-wrap { width: 100%; height: 6px; background: var(--surface-2); border-radius: 3px; overflow: hidden; margin-top: 10px; }
.disk-bar { height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.3s; }
.disk-bar.warn { background: #fbbf24; }
.disk-bar.crit { background: #ef4444; }
</style>
