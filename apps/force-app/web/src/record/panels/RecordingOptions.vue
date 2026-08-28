<script setup lang="ts">
import { computed, onMounted, watch } from 'vue';
import { useWorkspace } from '../workspace';
import LookupField from './LookupField.vue';
import CutPicker from './CutPicker.vue';
import StatTile from './StatTile.vue';

const w = useWorkspace();
// Surface speed (m/min) = pi * diam(mm) * rpm / 1000 — the same formula buildRunPayload() already
// logs to Directus as machining_cutting_speed_m_per_min, just surfaced here too.
const replaySurfaceSpeed = computed(() => (Math.PI * w.replay.diam * w.replay.rpm) / 1000);
// Depth of cut: the schema splits axial/radial: prefer radial (the conventional "depth of cut" in
// turning) and fall back to axial when only that was recorded.
const replayDepthOfCut = computed(() => w.machining.radial_doc || w.machining.axial_doc || '—');
function fmtDuration(sec: number): string {
	if (!Number.isFinite(sec) || sec <= 0) return '—';
	const m = Math.floor(sec / 60), s = Math.round(sec % 60);
	return m > 0 ? `${m}m ${s}s` : `${s}s`;
}
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

		<!-- ─── Sample, then its operation type — always first: this is "what am I recording/
			 replaying", the identity of the cut. ─── -->
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

		<!-- ─── Feed & speed — the key numeric readout, right after identity. For sim/nidaq this is
			 the editable recording config; for replay it's the picked cut's own recorded values, so
			 the cut picker (which supplies that data) sits immediately above it. ─── -->
		<template v-if="w.source.value === 'sim' || w.source.value === 'nidaq'">
			<div class="stat-grid">
				<StatTile editable label="Spindle" unit="RPM" v-model="w.cfg.rpm" :disabled="w.locked.value" />
				<StatTile editable label="Feed" unit="mm/rev" step="0.01" v-model="w.cfg.feed" :disabled="w.locked.value" />
				<StatTile editable label="Outer Ø" unit="mm" v-model="w.cfg.diam" :disabled="w.locked.value" />
				<StatTile editable label="Inner Ø" unit="mm" v-model="w.cfg.inner_diam" :disabled="w.locked.value" />
				<StatTile editable label="Sample rate" unit="Hz" v-model="w.cfg.sample_rate" :disabled="w.locked.value" />
				<StatTile editable :label="w.source.value === 'sim' ? 'Duration' : 'Planned duration'" unit="s"
					v-model="w.cfg.duration_sec" :disabled="w.locked.value"
					:title="w.source.value === 'sim' ? '' : 'Not enforced for real recordings — used only to estimate disk space needed and warn before you start.'" />
				<StatTile editable label="Pulses/rev" v-model="w.cfg.ppr" :disabled="w.locked.value" />
			</div>
		</template>

		<template v-if="w.source.value === 'replay'">
			<!-- Cut picker: filtered by Sample/Operation type above, further narrowed by free-text
				 search. Picking one loads that operation's full original metadata (below) and the
				 readout right here. -->
			<CutPicker />
			<!-- Read-only: :model-value, not v-model. These tiles never expose their input branch
				 (no `editable`), so nothing ever emits update:modelValue — v-model would need every
				 value here to be an assignable expression, which the derived ones (surface speed,
				 depth of cut, capture, cut time) are not. -->
			<div v-if="w.replay.cacheId" class="stat-grid cut-params">
				<StatTile label="Feed" unit="mm/rev" :model-value="w.replay.feed" />
				<StatTile label="Diameter" unit="mm" :model-value="w.replay.diam" />
				<StatTile label="Inner Ø" unit="mm" :model-value="w.replay.innerDiam" />
				<StatTile label="Pulses/rev" :model-value="w.replay.ppr" />
				<StatTile label="Surface speed" unit="m/min" :model-value="replaySurfaceSpeed.toFixed(1)" />
				<StatTile label="Depth of cut" unit="mm" :model-value="replayDepthOfCut" />
				<StatTile label="Capture" unit="kHz" :model-value="(w.replay.sampleRate / 1000).toFixed(1)" />
				<StatTile label="Cut time" :model-value="fmtDuration(w.playback.state.duration)" />
			</div>
		</template>

		<!-- ─── Everything else ─── -->
		<div class="section-divider"><span>Details</span></div>

		<div class="links pair">
			<LookupField v-model="w.link.equipmentId" :display-label="w.link.equipmentLabel" label="Machine" placeholder="search machine…"
				:search="w.searchEquipmentForOp" :disabled="w.locked.value" @select="(i: any) => (w.link.equipmentLabel = i.label)" />
			<LookupField v-model="w.link.operatorId" :display-label="w.link.operatorLabel" label="Operator" placeholder="search operator…"
				:search="w.searchOperators" :disabled="w.locked.value" @select="(i: any) => (w.link.operatorLabel = i.label)" />
		</div>

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

		<div class="links pair">
			<LookupField v-model="w.link.insertId" :display-label="w.link.insertLabel" label="Insert" placeholder="search insert code…"
				:search="w.searchInserts" :disabled="w.locked.value" @select="(i: any) => { w.link.insertLabel = i.label; w.link.edgeId = ''; w.link.edgeLabel = ''; }" />
			<LookupField v-model="w.link.edgeId" :display-label="w.link.edgeLabel" label="Edge" placeholder="search edge code…"
				:search="searchEdgesForInsert" :disabled="w.locked.value"
				@select="(i: any) => { w.link.edgeLabel = i.label; if (i.extra?.insertId) { w.link.insertId = i.extra.insertId; w.link.insertLabel = i.extra.insertLabel; } }" />
		</div>
		<div class="links">
			<LookupField v-model="w.link.toolId" :display-label="w.link.toolLabel" label="Tool" placeholder="search tool name…"
				:search="w.searchToolsForOp" :disabled="w.locked.value" @select="(i: any) => (w.link.toolLabel = i.label)" />
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
.stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
.stat-grid.cut-params { margin-top: -2px; }
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
/* Two lookups side by side (Machine|Operator, Insert|Edge) to save vertical space. Each LookupField
   is position:relative with its own absolute dropdown, so the grid columns don't clip the menus. */
.links.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 0 10px; }
.hint { font-size: 11.5px; color: var(--text-dim); margin: 0; }
.chks { display: flex; gap: 16px; margin-top: 4px; }
.chk { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text); cursor: pointer; }
.chk input { accent-color: var(--accent); }
</style>
