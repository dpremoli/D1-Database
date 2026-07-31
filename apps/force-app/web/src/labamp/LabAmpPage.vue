<script setup lang="ts">
// Dedicated Kistler LabAmp page: connection, operation mode, the per-channel sensor table, and a
// settings reference explaining each parameter with recommended values. Talks to the backend
// /labamp/* (which proxies the link-local amp; mock by default so this works without hardware).
import { onMounted, reactive, ref } from 'vue';
import { labamp, type LabAmpStatus, type SensorRow } from '../record/labampApi';

const status = ref<LabAmpStatus | null>(null);
const sensors = ref<SensorRow[]>([]);
const busy = ref(false);
const err = ref<string | null>(null);
const cfg = reactive({ base_url: '', channels: 8, mode: 'mock' });
const savedCfg = ref(false);

async function refresh() {
	busy.value = true; err.value = null;
	try {
		status.value = await labamp.status();
		Object.assign(cfg, { base_url: status.value.base_url, channels: status.value.channels, mode: status.value.config_mode });
		sensors.value = status.value.reachable ? (await labamp.sensors()).sensors : [];
	} catch (e: any) { err.value = e?.message || 'status failed'; } finally { busy.value = false; }
}
async function saveCfg() {
	busy.value = true; err.value = null;
	try { await labamp.setConfig({ base_url: cfg.base_url, channels: Number(cfg.channels), mode: cfg.mode }); savedCfg.value = true; setTimeout(() => (savedCfg.value = false), 1600); await refresh(); }
	catch (e: any) { err.value = e?.message || 'save failed'; } finally { busy.value = false; }
}
async function setMode(mode: 'MEASURE' | 'RESET') {
	busy.value = true; err.value = null;
	try { const r = await labamp.setMode(mode); if (status.value) status.value.mode = r.mode; }
	catch (e: any) { err.value = e?.message || 'set mode failed'; } finally { busy.value = false; }
}

const reference = [
	{ name: 'Operation mode', what: 'MEASURE actively integrates sensor charge into a force signal; RESET short-circuits the input and zeroes the integrator (drift reset).', rec: 'RESET between cuts to zero drift, MEASURE for the duration of a cut. The app sets RESET→MEASURE on start and RESET on stop.' },
	{ name: 'Sensitivity (pC/N)', what: 'Charge sensitivity of each dynamometer channel — how much charge the sensor produces per newton.', rec: 'Enter the exact value from the Kistler calibration certificate for your dynamometer (Fx/Fy and Fz usually differ, e.g. ≈ −7.9 and ≈ −3.7 pC/N).' },
	{ name: 'Measuring range', what: 'Full-scale force the channel resolves. A smaller range gives finer resolution but clips sooner.', rec: 'Pick the smallest range that clears your expected peak force with ~1.5× headroom.' },
	{ name: 'Physical quantity', what: 'The measured quantity for the channel.', rec: 'Force for a dynamometer channel.' },
	{ name: 'Low-pass filter', what: 'Rejects noise/vibration above the mechanical bandwidth of interest.', rec: 'Set above your highest force frequency of interest (tooth-passing + a margin), below the noise floor.' },
];
onMounted(refresh);
</script>

<template>
	<div class="labamp-page">
		<header class="head">
			<h1>Lab Amplifier</h1>
			<div class="conn" :class="{ ok: status?.reachable }">
				<span class="material-symbols-rounded">{{ status?.reachable ? 'link' : 'link_off' }}</span>
				{{ status?.reachable ? 'Connected' : 'Not connected' }}
				<span v-if="status?.mock" class="mock">mock</span>
			</div>
			<button class="ic" :disabled="busy" title="Refresh" @click="refresh"><span class="material-symbols-rounded">refresh</span></button>
		</header>

		<div class="grid">
			<section class="card">
				<h2>Connection</h2>
				<label>Amplifier URL<input v-model="cfg.base_url" placeholder="http://169.254.143.59" spellcheck="false" /></label>
				<div class="two">
					<label>Channels<input type="number" v-model.number="cfg.channels" /></label>
					<label>Source
						<select v-model="cfg.mode"><option value="mock">mock (no hardware)</option><option value="real">real amplifier</option></select>
					</label>
				</div>
				<p class="hint">The amp is link-local (e.g. <code>169.254.143.59</code>) and reachable only from the acquisition PC; the backend proxies it.</p>
				<button class="btn save" :disabled="busy" @click="saveCfg">{{ savedCfg ? 'Saved ✓' : 'Save connection' }}</button>
				<p v-if="err" class="err">{{ err }}</p>
			</section>

			<section class="card">
				<h2>Operation mode</h2>
				<div class="seg big">
					<button :class="{ on: status?.mode === 'MEASURE' }" :disabled="busy || !status?.reachable" @click="setMode('MEASURE')">MEASURE</button>
					<button :class="{ on: status?.mode === 'RESET' }" :disabled="busy || !status?.reachable" @click="setMode('RESET')">RESET</button>
				</div>
				<p class="hint">MEASURE integrates charge into force; RESET zeroes drift between cuts.</p>
				<a class="export" :href="labamp.exportUrl()" target="_blank" rel="noopener"><span class="material-symbols-rounded">download</span> Export full config</a>
			</section>

			<section class="card wide">
				<h2>Channels</h2>
				<table v-if="sensors.length">
					<thead><tr><th>Ch</th><th>Name</th><th>Serial</th><th>Quantity</th><th>Sensitivity (pC/N)</th><th>Range</th></tr></thead>
					<tbody>
						<tr v-for="s in sensors" :key="s.channel">
							<td>{{ s.channel }}</td><td>{{ s.name }}</td><td>{{ s.serialNumber }}</td>
							<td>{{ s.physicalQuantity }}</td><td>{{ s.sensitivity }}</td><td>{{ s.range }}</td>
						</tr>
					</tbody>
				</table>
				<p v-else class="hint">No channel data — connect the amplifier (or use mock) and refresh.</p>
			</section>

			<section class="card wide">
				<h2>Settings reference</h2>
				<div v-for="r in reference" :key="r.name" class="ref">
					<div class="ref-name">{{ r.name }}</div>
					<div class="ref-what">{{ r.what }}</div>
					<div class="ref-rec"><span class="material-symbols-rounded">check_circle</span>{{ r.rec }}</div>
				</div>
			</section>
		</div>
	</div>
</template>

<style scoped>
.labamp-page { min-height: 100vh; background: radial-gradient(1200px 600px at 50% -10%, var(--bg-2), var(--bg)); }
.head { display: flex; align-items: center; gap: 14px; padding: 20px 26px 14px; border-bottom: 1px solid var(--border); }
.head h1 { margin: 0; font-size: 22px; }
.conn { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; color: var(--text-dim); }
.conn.ok { color: #4ade80; }
.conn .material-symbols-rounded { font-size: 18px; }
.mock { font-size: 10px; font-weight: 700; text-transform: uppercase; color: #fbbf24; background: rgba(251,191,36,0.12); padding: 1px 6px; border-radius: 10px; }
.ic { margin-left: auto; display: inline-flex; width: 34px; height: 34px; align-items: center; justify-content: center; background: var(--surface); border: 1px solid var(--border); border-radius: 9px; color: var(--text); cursor: pointer; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; padding: 22px 26px; max-width: 1100px; }
.card { background: rgba(17,26,51,0.6); border: 1px solid var(--border); border-radius: 12px; padding: 18px; }
.card.wide { grid-column: 1 / -1; }
h2 { margin: 0 0 12px; font-size: 15px; }
label { display: block; font-size: 11.5px; color: var(--text-dim); margin-bottom: 12px; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
input, select { display: block; width: 100%; margin-top: 4px; padding: 8px 10px; font-size: 13px; color: var(--text); background: rgba(0,0,0,0.25); border: 1px solid var(--border); border-radius: 7px; }
.hint { font-size: 11.5px; color: var(--text-dim); line-height: 1.5; margin: 4px 0 12px; }
.hint code { font-family: var(--mono); color: var(--text); }
.seg { display: flex; gap: 4px; }
.seg.big button { flex: 1; padding: 12px; font-size: 13px; font-weight: 700; color: var(--text-dim); background: var(--surface); border: 1px solid var(--border); border-radius: 8px; cursor: pointer; }
.seg.big button.on { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
.seg.big button:disabled { opacity: 0.5; cursor: not-allowed; }
.export { display: inline-flex; align-items: center; gap: 5px; margin-top: 12px; font-size: 12.5px; color: var(--accent); text-decoration: none; }
.export .material-symbols-rounded { font-size: 16px; }
.btn.save { padding: 9px 16px; font-size: 13px; font-weight: 600; color: var(--accent-ink); background: var(--accent); border: none; border-radius: 8px; cursor: pointer; }
.err { color: var(--danger); font-size: 12px; margin: 8px 0 0; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--border); font-size: 12.5px; }
th { color: var(--text-dim); font-weight: 600; }
.ref { padding: 10px 0; border-bottom: 1px solid var(--border); }
.ref:last-child { border-bottom: 0; }
.ref-name { font-size: 13.5px; font-weight: 640; color: var(--text); }
.ref-what { font-size: 12.5px; color: var(--text-dim); margin: 3px 0; line-height: 1.5; }
.ref-rec { display: flex; align-items: flex-start; gap: 6px; font-size: 12.5px; color: #86efac; line-height: 1.5; }
.ref-rec .material-symbols-rounded { font-size: 15px; margin-top: 1px; }
</style>
