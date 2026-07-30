<script setup lang="ts">
// Metadata for the cut. Sample/Operator/Machine are Directus-backed typeaheads (linked as m2o on
// the run write-back); the rest ride in recorded_metadata. Stamped into the .mat + summary too.
import { useWorkspace } from '../workspace';
import LookupField from './LookupField.vue';
const w = useWorkspace();
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
</style>
