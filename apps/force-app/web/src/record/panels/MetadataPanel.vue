<script setup lang="ts">
// Metadata for the cut. Sample/Operator/Machine are Directus-backed typeaheads (linked as m2o on
// the run write-back); the rest ride in recorded_metadata. Stamped into the .mat + summary too.
import { ref } from 'vue';
import { useWorkspace } from '../workspace';
import LookupField from './LookupField.vue';
const w = useWorkspace();
const showAdvanced = ref(false);
const textFields: { key: string; label: string }[] = [
	{ key: 'operation', label: 'Operation / pass code' },
	{ key: 'op_type', label: 'Operation type' },
	{ key: 'insert', label: 'Insert' },
	{ key: 'edge_id', label: 'Edge ID' },
	{ key: 'tool', label: 'Tool' },
	{ key: 'coolant', label: 'Coolant' },
];
</script>

<template>
	<div class="meta">
		<div class="links">
			<LookupField v-model="w.link.sampleId" :display-label="w.link.sampleLabel" label="Sample" placeholder="search sample code…"
				:search="w.searchSamples" :disabled="w.locked.value" @select="w.onSelectSample" />
			<LookupField v-model="w.link.operatorId" :display-label="w.link.operatorLabel" label="Operator" placeholder="search operator…"
				:search="w.searchOperators" :disabled="w.locked.value" @select="(i) => (w.link.operatorLabel = i.label)" />
			<LookupField v-model="w.link.equipmentId" :display-label="w.link.equipmentLabel" label="Machine" placeholder="search machine…"
				:search="w.searchEquipment" :disabled="w.locked.value" @select="(i) => (w.link.equipmentLabel = i.label)" />
		</div>
		<div class="grid2">
			<label v-for="f in textFields" :key="f.key">{{ f.label }}
				<input v-model="w.meta[f.key]" :disabled="w.locked.value" />
			</label>
		</div>
		<label class="wide">Notes
			<textarea v-model="w.meta.notes" rows="2" :disabled="w.locked.value"></textarea>
		</label>

		<button class="disclose" type="button" @click="showAdvanced = !showAdvanced">
			<span class="material-symbols-rounded">{{ showAdvanced ? 'expand_less' : 'expand_more' }}</span>
			Machining details (Directus form fields)
		</button>
		<div v-if="showAdvanced" class="advanced">
			<div class="grid2">
				<label>Axial DoC (mm)<input type="number" step="0.01" v-model="w.machining.axial_doc" :disabled="w.locked.value" /></label>
				<label>Radial DoC (mm)<input type="number" step="0.01" v-model="w.machining.radial_doc" :disabled="w.locked.value" /></label>
				<label>Cutting length (mm)<input type="number" v-model="w.machining.cutting_length" :disabled="w.locked.value" /></label>
				<label>Coolant pressure (bar)<input type="number" step="0.1" v-model="w.machining.coolant_pressure" :disabled="w.locked.value" /></label>
				<label>Operation sequence<input type="number" v-model="w.machining.operation_sequence" :disabled="w.locked.value" /></label>
				<label>Chips ref code<input v-model="w.machining.chips_ref" :disabled="w.locked.value" /></label>
			</div>
			<div class="chks">
				<label class="chk"><input type="checkbox" v-model="w.machining.new_edge" :disabled="w.locked.value" /> New edge</label>
				<label class="chk"><input type="checkbox" v-model="w.machining.chips_collected" :disabled="w.locked.value" /> Chips collected</label>
			</div>
		</div>
	</div>
</template>

<style scoped>
.meta { display: flex; flex-direction: column; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 10px; }
label { display: block; font-size: 11.5px; color: var(--text-dim); margin-bottom: 8px; }
label.wide { display: block; }
input, textarea { display: block; width: 100%; margin-top: 3px; padding: 7px 9px; font-size: 13px; color: var(--text); background: rgba(0,0,0,0.25); border: 1px solid var(--border); border-radius: 7px; outline: none; font-family: inherit; resize: vertical; }
input:focus, textarea:focus { border-color: var(--accent); }
input:disabled, textarea:disabled { opacity: 0.55; }
.disclose { display: flex; align-items: center; gap: 6px; margin-top: 4px; padding: 8px 4px; width: 100%; font-size: 12px; font-weight: 600; color: var(--accent); background: transparent; border: none; border-top: 1px solid var(--border); cursor: pointer; }
.disclose .material-symbols-rounded { font-size: 18px; }
.advanced { padding-top: 6px; }
.chks { display: flex; gap: 16px; margin-top: 4px; }
.chk { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text); cursor: pointer; }
.chk input { accent-color: var(--accent); }
</style>
