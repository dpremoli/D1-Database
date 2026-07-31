<script setup lang="ts">
import { computed, onMounted, watch } from 'vue';
import { useWorkspace } from '../workspace';

const w = useWorkspace();
const ss = w.syncStatus;
const syncText = computed(() => {
	if (ss.syncing) return 'Syncing…';
	if (ss.pending > 0) return `Queued offline · ${ss.pending} pending`;
	if (ss.lastError) return ss.lastError;
	if (ss.lastSyncedAt) return 'Synced to database';
	return '';
});
const syncClass = computed(() => (ss.pending > 0 ? 'warn' : ss.lastError ? 'err' : ss.lastSyncedAt ? 'ok' : ''));
const syncIcon = computed(() => (ss.pending > 0 ? 'cloud_queue' : ss.lastError ? 'error' : ss.lastSyncedAt ? 'cloud_done' : 'cloud'));
let t: any = null;
function onSearch() { clearTimeout(t); t = setTimeout(() => w.searchCuts(w.replay.query), 300); }
watch(() => w.source.value, (s) => { if (s === 'replay' && w.replay.options.length === 0) w.searchCuts(''); });
onMounted(() => { if (w.source.value === 'replay') w.searchCuts(''); });
</script>

<template>
	<div class="opts">
		<div class="seg">
			<button :class="{ on: w.source.value === 'sim' }" :disabled="w.locked.value" @click="w.source.value = 'sim'">Simulated</button>
			<button :class="{ on: w.source.value === 'replay' }" :disabled="w.locked.value" @click="w.source.value = 'replay'">Replay file</button>
			<button :class="{ on: w.source.value === 'nidaq' }" :disabled="w.locked.value" @click="w.source.value = 'nidaq'">NI-DAQ</button>
		</div>

		<template v-if="w.source.value === 'sim' || w.source.value === 'nidaq'">
			<div class="grid2">
				<label>Spindle (RPM)<input type="number" v-model.number="w.cfg.rpm" :disabled="w.locked.value" /></label>
				<label>Feed (mm/rev)<input type="number" step="0.01" v-model.number="w.cfg.feed" :disabled="w.locked.value" /></label>
				<label>Outer Ø (mm)<input type="number" v-model.number="w.cfg.diam" :disabled="w.locked.value" /></label>
				<label>Inner Ø (mm)<input type="number" v-model.number="w.cfg.inner_diam" :disabled="w.locked.value" /></label>
				<label>Sample rate (Hz)<input type="number" v-model.number="w.cfg.sample_rate" :disabled="w.locked.value" /></label>
				<label v-if="w.source.value === 'sim'">Duration (s)<input type="number" v-model.number="w.cfg.duration_sec" :disabled="w.locked.value" /></label>
				<label>Pulses/rev<input type="number" v-model.number="w.cfg.ppr" :disabled="w.locked.value" /></label>
			</div>
		</template>

		<template v-if="w.source.value === 'nidaq'">
			<label>NI-DAQ channels <span class="sub">(Fx1,Fx2,Fy1,Fy2,Fz1,Fz2,Fz3,Fz4,Tacho)</span>
				<textarea v-model="w.nidaqChannels.value" rows="9" spellcheck="false" :disabled="w.locked.value"></textarea>
			</label>
			<p class="hint warn"><span class="material-symbols-rounded">warning</span> Hardware acquisition — records until you press Stop. Set your rig's real device/channel strings; this path is built from the MATLAB method but untested against hardware (validate on the rig).</p>
		</template>

		<template v-if="w.source.value === 'replay'">
			<label>Find a cut
				<input v-model="w.replay.query" placeholder="e.g. 10-AA-MF" :disabled="w.locked.value" @input="onSearch" />
			</label>
			<div class="cutlist">
				<div v-if="w.replay.loading" class="hint">searching…</div>
				<button v-for="o in w.replay.options" :key="o.cacheId" class="cut" :class="{ on: w.replay.cacheId === o.cacheId }"
					:disabled="w.locked.value" @click="w.replay.cacheId = o.cacheId; w.replay.label = o.label; w.meta.sample_name = o.label">
					{{ o.label }}
				</button>
				<div v-if="!w.replay.loading && w.replay.options.length === 0" class="hint">no matches</div>
			</div>
			<label>Replay speed ×<input type="number" v-model.number="w.replay.speed" min="1" :disabled="w.locked.value" /></label>
		</template>

		<div class="actions">
			<button v-if="!w.locked.value" class="btn start" :disabled="w.busy.value || !w.st.connected" @click="w.start()">
				<span class="material-symbols-rounded">fiber_manual_record</span> Start
			</button>
			<button v-else class="btn stop" :disabled="w.busy.value || w.isFinalizing.value" @click="w.stop()">
				<span class="material-symbols-rounded">stop</span> {{ w.isFinalizing.value ? 'Finalizing…' : 'Stop' }}
			</button>
			<button v-if="w.isDone.value" class="btn ghost" @click="w.newRun()">New</button>
		</div>
		<p v-if="w.errMsg.value" class="err">{{ w.errMsg.value }}</p>
		<p v-if="w.st.state === 'error' && w.st.error" class="err">{{ w.st.error.split('\n')[0] }}</p>

		<div v-if="w.isDone.value" class="logrun">
			<button class="btn save" :disabled="!w.link.sampleId || w.logged.value" @click="w.logRunNow()">
				<span class="material-symbols-rounded">cloud_upload</span> {{ w.logged.value ? 'Logged' : 'Log run to database' }}
			</button>
			<p v-if="!w.link.sampleId" class="hint">Pick a Sample in Metadata to enable logging.</p>
			<p v-if="syncText" class="sync" :class="syncClass"><span class="material-symbols-rounded">{{ syncIcon }}</span>{{ syncText }}</p>
		</div>
	</div>
</template>

<style scoped>
.opts { display: flex; flex-direction: column; gap: 10px; }
.seg { display: flex; gap: 0; border: 1px solid var(--border); border-radius: 9px; overflow: hidden; }
.seg button { flex: 1; padding: 8px; font-size: 12.5px; background: transparent; color: var(--text-dim); border: none; cursor: pointer; }
.seg button.on { background: var(--accent); color: var(--accent-ink); font-weight: 600; }
.seg button:disabled { opacity: 0.5; cursor: not-allowed; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 10px; }
label { display: block; font-size: 11.5px; color: var(--text-dim); margin-bottom: 8px; }
input, textarea { display: block; width: 100%; margin-top: 3px; padding: 7px 9px; font-size: 13px; color: var(--text); background: rgba(0,0,0,0.25); border: 1px solid var(--border); border-radius: 7px; outline: none; font-family: inherit; }
textarea { font-family: var(--mono); font-size: 12px; resize: vertical; }
input:focus, textarea:focus { border-color: var(--accent); }
input:disabled, textarea:disabled { opacity: 0.55; }
.sub { color: var(--text-dim); font-weight: 400; font-size: 10.5px; }
.hint.warn { display: flex; align-items: flex-start; gap: 5px; color: #fbbf24; }
.hint.warn .material-symbols-rounded { font-size: 15px; margin-top: 1px; }
.cutlist { max-height: 160px; overflow: auto; display: flex; flex-direction: column; gap: 4px; border: 1px solid var(--border); border-radius: 8px; padding: 5px; }
.cut { text-align: left; padding: 6px 8px; font-size: 12px; font-family: var(--mono); color: var(--text); background: transparent; border: 1px solid transparent; border-radius: 6px; cursor: pointer; }
.cut:hover { background: var(--surface); }
.cut.on { background: rgba(56,189,248,0.16); border-color: var(--accent); }
.hint { font-size: 12px; color: var(--text-dim); padding: 6px; }
.actions { display: flex; gap: 8px; margin-top: 4px; }
.btn { display: inline-flex; align-items: center; gap: 6px; padding: 9px 14px; font-size: 13.5px; font-weight: 600; border: none; border-radius: 8px; cursor: pointer; }
.btn .material-symbols-rounded { font-size: 18px; }
.btn.start { background: #22c55e; color: #05210f; }
.btn.stop { background: #ef4444; color: #2a0808; }
.btn.save { background: var(--accent); color: var(--accent-ink); }
.btn.ghost { background: var(--surface); color: var(--text); border: 1px solid var(--border); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.err { color: var(--danger); font-size: 12px; margin: 4px 0 0; }
.logrun { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 6px; }
.hint { font-size: 11.5px; color: var(--text-dim); margin: 0; }
.sync { display: flex; align-items: center; gap: 5px; font-size: 12px; margin: 0; }
.sync .material-symbols-rounded { font-size: 16px; }
.sync.ok { color: #4ade80; }
.sync.warn { color: #fbbf24; }
.sync.err { color: var(--danger); }
</style>
