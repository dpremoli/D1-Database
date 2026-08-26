<script setup lang="ts">
import { computed, onMounted, watch } from 'vue';
import { useWorkspace } from '../workspace';
import LookupField from './LookupField.vue';
import TransportBar from './TransportBar.vue';

const w = useWorkspace();
let t: any = null;
function onSearch() { clearTimeout(t); t = setTimeout(() => w.searchCuts(w.replay.query), 300); }
watch(() => w.source.value, (s) => { if (s === 'replay' && w.replay.options.length === 0) w.searchCuts(''); });
onMounted(() => { if (w.source.value === 'replay') w.searchCuts(''); });
// The cut list is also progressively filtered by Sample/Operation type/Machine (see
// workspace.ts's searchCuts) — re-run whenever any of those change while replay is active, so
// narrowing the metadata fields narrows the list live, not just on the next text search.
watch(() => [w.link.sampleId, w.link.equipmentId, w.meta.op_type], () => {
	if (w.source.value === 'replay') w.searchCuts(w.replay.query);
});

const MACHINING_SUBTYPES = [
	{ value: 'MT-F', text: 'Turning – Facing' },
	{ value: 'MT-R', text: 'Turning – Roughing' },
	{ value: 'MT-O', text: 'Turning – OD' },
	{ value: 'MT-G', text: 'Turning – Grooving' },
	{ value: 'MT-B', text: 'Turning – Boring' },
	{ value: 'MT-H', text: 'Turning – Threading' },
	{ value: 'MT-P', text: 'Turning – Parting' },
	{ value: 'MT-D', text: 'Turning – Drilling' },
	{ value: 'MM-F', text: 'Milling – Facing' },
	{ value: 'MM-R', text: 'Milling – Roughing' },
	{ value: 'MM-S', text: 'Milling – Slotting' },
	{ value: 'MM-D', text: 'Milling – Drilling' },
	{ value: 'other', text: 'Other' },
] as const;
function searchEdgesForInsert(q: string) { return w.searchEdges(q, w.link.insertId || undefined); }
</script>

<template>
	<div class="opts">
		<!-- Source selector -->
		<div class="seg">
			<button :class="{ on: w.source.value === 'sim' }" :disabled="w.locked.value" @click="w.setSource('sim')">Simulated</button>
			<button :class="{ on: w.source.value === 'replay' }" :disabled="w.locked.value" @click="w.setSource('replay')">Replay file</button>
			<button :class="{ on: w.source.value === 'nidaq' }" :disabled="w.locked.value" @click="w.setSource('nidaq')">NI-DAQ</button>
		</div>

		<!-- Recording parameters -->
		<template v-if="w.source.value === 'sim' || w.source.value === 'nidaq'">
			<div class="grid2">
				<label>Spindle (RPM)<input type="number" v-model.number="w.cfg.rpm" :disabled="w.locked.value" /></label>
				<label>Feed (mm/rev)<input type="number" step="0.01" v-model.number="w.cfg.feed" :disabled="w.locked.value" /></label>
				<label>Outer Ø (mm)<input type="number" v-model.number="w.cfg.diam" :disabled="w.locked.value" /></label>
				<label>Inner Ø (mm)<input type="number" v-model.number="w.cfg.inner_diam" :disabled="w.locked.value" /></label>
				<label>Sample rate (Hz)<input type="number" v-model.number="w.cfg.sample_rate" :disabled="w.locked.value" /></label>
				<label>
					{{ w.source.value === 'sim' ? 'Duration (s)' : 'Planned duration (s)' }}
					<input type="number" v-model.number="w.cfg.duration_sec" :disabled="w.locked.value"
						:title="w.source.value === 'sim' ? '' : 'Not enforced for real recordings — used only to estimate disk space needed and warn before you start.'" />
				</label>
				<label>Pulses/rev<input type="number" v-model.number="w.cfg.ppr" :disabled="w.locked.value" /></label>
			</div>
		</template>

		<!-- NI-DAQ channel summary (configured in Settings) -->
		<p v-if="w.source.value === 'nidaq'" class="hint nidaq-hint">
			<span class="material-symbols-rounded">memory</span>
			{{ w.nidaqChannels.value.split(/[\n,]+/).filter(Boolean).length }} channels configured
			<span class="sub">(edit in Settings)</span>
		</p>

		<!-- Processing options -->
		<div v-if="w.source.value !== 'replay'" class="proc">
			<label class="chk"><input type="checkbox" v-model="w.cfg.frm_from_cut" :disabled="w.locked.value" /> Detect cut start (live FRM begins at the cut)</label>
			<label class="chk"><input type="checkbox" v-model="w.cfg.drift_comp" :disabled="w.locked.value" /> Drift compensation <span class="sub">(saved outputs only — raw stays raw)</span></label>
			<label class="chk"><input type="checkbox" v-model="w.converge.enabled" :disabled="w.locked.value" /> Converging auto-range <span class="sub">(tune per-channel ranges between cuts)</span></label>
			<p v-if="w.converge.enabled && w.source.value !== 'nidaq'" class="hint">Applies live only with the NI-DAQ source; on sim/replay it just previews the recommendation.</p>
			<p v-if="w.converge.status" class="sync" :class="w.converge.busy ? 'warn' : 'ok'"><span class="material-symbols-rounded">tune</span>{{ w.converge.status }}</p>
		</div>

		<!-- ─── Metadata ─── -->
		<!-- Sample -> Operation type -> Machine first: for a replay, these three progressively
			 filter the cut list right below Machine (see workspace.ts's searchCuts); for sim/nidaq
			 there's no cut list, so this just flows straight into Tool/Operator/Insert/Edge. -->
		<div class="section-divider"><span>Metadata</span></div>

		<div class="links">
			<LookupField v-model="w.link.sampleId" :display-label="w.link.sampleLabel" label="Sample" placeholder="search sample code…"
				:search="w.searchSamples" :disabled="w.locked.value" @select="w.onSelectSample" />
		</div>
		<div class="grid2">
			<label>Operation type
				<select v-model="w.meta.op_type" :disabled="w.locked.value">
					<option value="">—</option>
					<option v-for="t in MACHINING_SUBTYPES" :key="t.value" :value="t.value">{{ t.text }}</option>
				</select>
			</label>
		</div>
		<div class="links">
			<LookupField v-model="w.link.equipmentId" :display-label="w.link.equipmentLabel" label="Machine" placeholder="search machine…"
				:search="w.searchEquipmentForOp" :disabled="w.locked.value" @select="(i: any) => (w.link.equipmentLabel = i.label)" />
		</div>

		<!-- Replay cut picker: filtered by Sample/Operation type/Machine above, further narrowed by
			 free-text search. Picking one loads that operation's full original metadata (below). -->
		<template v-if="w.source.value === 'replay'">
			<label>Find a cut <span class="sub">(narrowed by Sample/Operation type/Machine above)</span>
				<input v-model="w.replay.query" placeholder="e.g. 10-AA-MF" :disabled="w.locked.value" @input="onSearch" />
			</label>
			<div class="cutlist">
				<div v-if="w.replay.loading" class="hint">searching…</div>
				<button v-for="o in w.replay.options" :key="o.cacheId" class="cut" :class="{ on: w.replay.cacheId === o.cacheId }"
					:disabled="w.locked.value" @click="w.pickReplayCut(o)">
					{{ o.label }}
				</button>
				<div v-if="!w.replay.loading && w.replay.options.length === 0" class="hint">no matches</div>
			</div>
		</template>

		<div class="links">
			<LookupField v-model="w.link.toolId" :display-label="w.link.toolLabel" label="Tool" placeholder="search tool code…"
				:search="w.searchToolsForOp" :disabled="w.locked.value" @select="(i: any) => (w.link.toolLabel = i.label)" />
			<LookupField v-model="w.link.operatorId" :display-label="w.link.operatorLabel" label="Operator" placeholder="search operator…"
				:search="w.searchOperators" :disabled="w.locked.value" @select="(i: any) => (w.link.operatorLabel = i.label)" />
		</div>
		<div class="links">
			<LookupField v-model="w.link.insertId" :display-label="w.link.insertLabel" label="Insert" placeholder="search insert code…"
				:search="w.searchInserts" :disabled="w.locked.value" @select="(i: any) => { w.link.insertLabel = i.label; w.link.edgeId = ''; w.link.edgeLabel = ''; }" />
			<LookupField v-model="w.link.edgeId" :display-label="w.link.edgeLabel" label="Edge" placeholder="search edge code…"
				:search="searchEdgesForInsert" :disabled="w.locked.value" @select="(i: any) => (w.link.edgeLabel = i.label)" />
		</div>
		<div class="grid2">
			<label>Coolant<input v-model="w.meta.coolant" :disabled="w.locked.value" /></label>
			<label>Coolant pressure (bar)<input type="number" step="0.1" v-model="w.machining.coolant_pressure" :disabled="w.locked.value" /></label>
			<label>Axial DoC (mm)<input type="number" step="0.01" v-model="w.machining.axial_doc" :disabled="w.locked.value" /></label>
			<label>Radial DoC (mm)<input type="number" step="0.01" v-model="w.machining.radial_doc" :disabled="w.locked.value" /></label>
			<label>Cutting length (mm)<input type="number" v-model="w.machining.cutting_length" :disabled="w.locked.value" /></label>
			<label>Chips ref code<input v-model="w.machining.chips_ref" :disabled="w.locked.value" /></label>
		</div>
		<div class="chks">
			<label class="chk"><input type="checkbox" v-model="w.machining.new_edge" :disabled="w.locked.value" /> New edge</label>
			<label class="chk"><input type="checkbox" v-model="w.machining.chips_collected" :disabled="w.locked.value" /> Chips collected</label>
		</div>
		<label class="wide">Notes
			<textarea v-model="w.meta.notes" rows="2" :disabled="w.locked.value"></textarea>
		</label>

		<!-- ─── Actions ─── -->
		<TransportBar v-if="w.mode.value === 'playback'" />
		<div v-else class="actions">
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

	</div>
</template>

<style scoped>
/* No overflow/max-height here: PanelFrame's own .panel-body is already the scroll container.
   Nesting a second auto-overflow box inside it let the two end up with independent scroll
   positions — the outer at 0 while this one had scrolled itself, which read as the very top row
   (the Simulated/Replay/NI-DAQ source buttons) being clipped even though the panel was at rest. */
.opts { display: flex; flex-direction: column; gap: 10px; }
.seg { display: flex; gap: 0; border: 1px solid var(--border); border-radius: 9px; overflow: hidden; }
.seg button { flex: 1; padding: 8px; font-size: 12.5px; background: transparent; color: var(--text-dim); border: none; cursor: pointer; }
.seg button.on { background: var(--accent); color: var(--accent-ink); font-weight: 600; }
.seg button:disabled { opacity: 0.5; cursor: not-allowed; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 10px; }
label { display: block; font-size: 11.5px; color: var(--text-dim); margin-bottom: 8px; }
label.wide { display: block; }
input:not([type="checkbox"]), textarea, select { display: block; width: 100%; margin-top: 3px; padding: 7px 9px; font-size: 13px; color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: 7px; outline: none; font-family: inherit; }
select option { background: var(--bg); color: var(--text); }
textarea { font-family: var(--mono); font-size: 12px; resize: vertical; }
input:focus, textarea:focus, select:focus { border-color: var(--accent); }
input:disabled, textarea:disabled, select:disabled { opacity: 0.55; }
.sub { color: var(--text-dim); font-weight: 400; font-size: 10.5px; }
.nidaq-hint { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-dim); }
.nidaq-hint .material-symbols-rounded { font-size: 16px; color: var(--accent); }
.proc { display: flex; flex-direction: column; gap: 7px; padding: 8px 0 2px; border-top: 1px solid var(--border); }
.proc .chk { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--text); cursor: pointer; margin-bottom: 0; }
.proc .chk input { accent-color: var(--accent); }
.section-divider { display: flex; align-items: center; gap: 10px; margin: 6px 0 2px; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-dim); }
.section-divider::before, .section-divider::after { content: ''; flex: 1; height: 1px; background: var(--border); }
.links { display: flex; flex-direction: column; }
.cutlist { max-height: 160px; overflow: auto; display: flex; flex-direction: column; gap: 4px; border: 1px solid var(--border); border-radius: 8px; padding: 5px; }
.cut { text-align: left; padding: 6px 8px; font-size: 12px; font-family: var(--mono); color: var(--text); background: transparent; border: 1px solid transparent; border-radius: 6px; cursor: pointer; }
.cut:hover { background: var(--surface); }
.cut.on { background: rgba(56,189,248,0.16); border-color: var(--accent); }
.hint { font-size: 11.5px; color: var(--text-dim); margin: 0; }
.actions { display: flex; gap: 8px; margin-top: 4px; }
.btn { display: inline-flex; align-items: center; gap: 6px; padding: 9px 14px; font-size: 13.5px; font-weight: 600; border: none; border-radius: 8px; cursor: pointer; }
.btn .material-symbols-rounded { font-size: 18px; }
.btn.start { background: #22c55e; color: #05210f; }
.btn.stop { background: #ef4444; color: #2a0808; }
.btn.save { background: var(--accent); color: var(--accent-ink); }
.btn.ghost { background: var(--surface); color: var(--text); border: 1px solid var(--border); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.err { color: var(--danger); font-size: 12px; margin: 4px 0 0; }
.chks { display: flex; gap: 16px; margin-top: 4px; }
.chk { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text); cursor: pointer; }
.chk input { accent-color: var(--accent); }
</style>
