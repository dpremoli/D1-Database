<script setup lang="ts">
// Kistler LabAmp control (slice 2c). Talks to the backend /labamp/* (which proxies the link-local
// amp; mock by default so this works without hardware). Shows connection + mode, lets the operator
// set MEASURE/RESET, view the per-sensor table, and configure the amp IP / mock-vs-real.
import { onMounted, ref } from 'vue';
import { labamp, type LabAmpStatus, type SensorRow } from '../labampApi';

const status = ref<LabAmpStatus | null>(null);
const sensors = ref<SensorRow[]>([]);
const busy = ref(false);
const err = ref<string | null>(null);
const showCfg = ref(false);
const cfg = ref({ base_url: '', channels: 8, mode: 'mock' });

async function refresh() {
	busy.value = true; err.value = null;
	try {
		status.value = await labamp.status();
		cfg.value = { base_url: status.value.base_url, channels: status.value.channels, mode: status.value.config_mode };
		if (status.value.reachable) sensors.value = (await labamp.sensors()).sensors;
		else sensors.value = [];
	} catch (e: any) { err.value = e?.message || 'status failed'; } finally { busy.value = false; }
}
async function setMode(mode: 'MEASURE' | 'RESET') {
	busy.value = true; err.value = null;
	try { const r = await labamp.setMode(mode); if (status.value) status.value.mode = r.mode; }
	catch (e: any) { err.value = e?.message || 'set mode failed'; } finally { busy.value = false; }
}
async function saveCfg() {
	busy.value = true; err.value = null;
	try { await labamp.setConfig({ base_url: cfg.value.base_url, channels: Number(cfg.value.channels), mode: cfg.value.mode }); showCfg.value = false; await refresh(); }
	catch (e: any) { err.value = e?.message || 'save failed'; } finally { busy.value = false; }
}
onMounted(refresh);
</script>

<template>
	<div class="labamp">
		<div class="top">
			<div class="conn" :class="{ ok: status?.reachable }">
				<span class="material-symbols-rounded">{{ status?.reachable ? 'link' : 'link_off' }}</span>
				{{ status?.reachable ? 'Connected' : 'Not connected' }}
				<span v-if="status?.mock" class="mock">mock</span>
			</div>
			<button class="ic" title="Refresh" :disabled="busy" @click="refresh"><span class="material-symbols-rounded">refresh</span></button>
			<button class="ic" title="Settings" @click="showCfg = !showCfg"><span class="material-symbols-rounded">settings</span></button>
		</div>
		<div class="addr">{{ status?.base_url }}</div>

		<div v-if="showCfg" class="cfg">
			<label>Amp URL<input v-model="cfg.base_url" placeholder="http://169.254.143.59" /></label>
			<div class="cfg2">
				<label>Channels<input type="number" v-model.number="cfg.channels" /></label>
				<label>Source
					<select v-model="cfg.mode"><option value="mock">mock</option><option value="real">real amp</option></select>
				</label>
			</div>
			<button class="btn save" :disabled="busy" @click="saveCfg">Save</button>
		</div>

		<div class="mode">
			<span class="lbl">Mode</span>
			<div class="seg">
				<button :class="{ on: status?.mode === 'MEASURE' }" :disabled="busy || !status?.reachable" @click="setMode('MEASURE')">MEASURE</button>
				<button :class="{ on: status?.mode === 'RESET' }" :disabled="busy || !status?.reachable" @click="setMode('RESET')">RESET</button>
			</div>
		</div>

		<div class="sensors" v-if="sensors.length">
			<table>
				<thead><tr><th>Ch</th><th>Name</th><th>Qty</th><th>Sens.</th><th>Range</th></tr></thead>
				<tbody>
					<tr v-for="s in sensors" :key="s.channel">
						<td>{{ s.channel }}</td><td>{{ s.name }}</td><td>{{ s.physicalQuantity }}</td>
						<td>{{ s.sensitivity }}</td><td>{{ s.range }}</td>
					</tr>
				</tbody>
			</table>
			<a class="export" :href="labamp.exportUrl()" target="_blank" rel="noopener"><span class="material-symbols-rounded">download</span> Export config</a>
		</div>
		<p v-if="err" class="err">{{ err }}</p>
	</div>
</template>

<style scoped>
.labamp { display: flex; flex-direction: column; gap: 9px; font-size: 12.5px; }
.top { display: flex; align-items: center; gap: 8px; }
.conn { display: flex; align-items: center; gap: 6px; font-weight: 600; color: var(--text-dim); }
.conn.ok { color: #4ade80; }
.conn .material-symbols-rounded { font-size: 17px; }
.mock { font-size: 10px; font-weight: 700; text-transform: uppercase; color: #fbbf24; background: rgba(251,191,36,0.12); padding: 1px 6px; border-radius: 10px; }
.ic { margin-left: auto; display: inline-flex; width: 28px; height: 28px; align-items: center; justify-content: center; background: var(--surface); border: 1px solid var(--border); border-radius: 7px; color: var(--text); cursor: pointer; }
.ic + .ic { margin-left: 0; }
.addr { font-family: var(--mono); font-size: 11px; color: var(--text-dim); }
.cfg { display: flex; flex-direction: column; gap: 7px; padding: 9px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; }
.cfg2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
label { display: block; font-size: 11px; color: var(--text-dim); }
input, select { display: block; width: 100%; margin-top: 3px; padding: 6px 8px; font-size: 12.5px; color: var(--text); background: rgba(0,0,0,0.25); border: 1px solid var(--border); border-radius: 6px; }
.mode { display: flex; align-items: center; gap: 10px; }
.mode .lbl { font-size: 11.5px; color: var(--text-dim); }
.seg { display: flex; gap: 4px; }
.seg button { padding: 6px 14px; font-size: 12px; font-weight: 600; color: var(--text-dim); background: var(--surface); border: 1px solid var(--border); border-radius: 7px; cursor: pointer; }
.seg button.on { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
.seg button:disabled { opacity: 0.5; cursor: not-allowed; }
.sensors table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
.sensors th, .sensors td { text-align: left; padding: 4px 6px; border-bottom: 1px solid var(--border); font-size: 11.5px; }
.sensors th { color: var(--text-dim); font-weight: 600; }
.export { display: inline-flex; align-items: center; gap: 5px; margin-top: 8px; font-size: 12px; color: var(--accent); text-decoration: none; }
.export .material-symbols-rounded { font-size: 15px; }
.btn.save { padding: 7px 12px; font-size: 12.5px; font-weight: 600; color: var(--accent-ink); background: var(--accent); border: none; border-radius: 7px; cursor: pointer; }
.err { color: var(--danger); font-size: 12px; margin: 0; }
</style>
