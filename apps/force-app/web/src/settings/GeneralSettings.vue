<script setup lang="ts">
// Service endpoints — editable at runtime, saved to a localStorage override so the same bundle can
// be repointed at a different backend without a rebuild.
import { reactive, ref } from 'vue';
import { getConfig, getConfigDefaults, setConfigOverride, resetConfigOverride } from '../config';

const fields: { key: 'directusUrl' | 'filterUrl' | 'octreeUrl' | 'recorderUrl'; label: string; hint: string }[] = [
	{ key: 'directusUrl', label: 'Directus URL', hint: 'REST base for items, assets and auth.' },
	{ key: 'filterUrl', label: 'Filter service URL', hint: 'Signal-filter sidecar (/run, /fft).' },
	{ key: 'octreeUrl', label: 'Octree server URL', hint: 'Potree LOD octree static host.' },
	{ key: 'recorderUrl', label: 'Recorder URL', hint: 'Local recording/acquisition backend + Lab Amp proxy.' },
];
const form = reactive({ ...getConfig() });
const saved = ref(false);
const testResult = ref<Record<string, string>>({});

function save() { setConfigOverride({ ...form }); saved.value = true; setTimeout(() => (saved.value = false), 1800); }
function reset() { resetConfigOverride(); Object.assign(form, getConfigDefaults()); saved.value = false; testResult.value = {}; }

async function test() {
	testResult.value = {};
	const checks: [string, string][] = [
		['recorderUrl', `${form.recorderUrl}/health`],
		['directusUrl', `${form.directusUrl}/server/ping`],
	];
	for (const [key, url] of checks) {
		try { const r = await fetch(url, { method: 'GET' }); testResult.value[key] = r.ok ? 'ok' : `HTTP ${r.status}`; }
		catch { testResult.value[key] = 'unreachable'; }
	}
}
</script>

<template>
	<div class="general">
		<h2>Service endpoints</h2>
		<p class="lead">Where the app finds Directus and the local services. Changes are saved to this browser and apply to new requests immediately.</p>
		<label v-for="f in fields" :key="f.key" class="field">
			<span class="lbl">{{ f.label }} <span v-if="testResult[f.key]" class="test" :class="{ ok: testResult[f.key] === 'ok' }">{{ testResult[f.key] }}</span></span>
			<input v-model="form[f.key]" spellcheck="false" />
			<span class="hint">{{ f.hint }}</span>
		</label>
		<div class="actions">
			<button class="btn save" @click="save">{{ saved ? 'Saved ✓' : 'Save' }}</button>
			<button class="btn ghost" @click="test">Test connections</button>
			<button class="btn ghost" @click="reset">Reset to defaults</button>
		</div>
	</div>
</template>

<style scoped>
.general { max-width: 620px; }
h2 { margin: 0 0 4px; font-size: 16px; }
.lead { margin: 0 0 18px; font-size: 13px; color: var(--text-dim); line-height: 1.5; }
.field { display: block; margin-bottom: 16px; }
.lbl { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text); margin-bottom: 5px; }
.test { font-size: 10.5px; font-weight: 700; padding: 1px 7px; border-radius: 10px; color: var(--danger); background: rgba(252,165,165,0.12); }
.test.ok { color: #4ade80; background: rgba(74,222,128,0.12); }
input { display: block; width: 100%; padding: 9px 11px; font-size: 13px; font-family: var(--mono); color: var(--text); background: rgba(0,0,0,0.25); border: 1px solid var(--border); border-radius: 8px; outline: none; }
input:focus { border-color: var(--accent); }
.hint { display: block; font-size: 11.5px; color: var(--text-dim); margin-top: 4px; }
.actions { display: flex; gap: 10px; margin-top: 6px; }
.btn { padding: 9px 16px; font-size: 13px; font-weight: 600; border: none; border-radius: 8px; cursor: pointer; }
.btn.save { background: var(--accent); color: var(--accent-ink); }
.btn.ghost { background: var(--surface); color: var(--text); border: 1px solid var(--border); }
</style>
