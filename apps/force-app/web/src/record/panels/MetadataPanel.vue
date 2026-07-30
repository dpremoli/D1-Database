<script setup lang="ts">
// Metadata compiled for the cut (stamped into the .mat + summary; Directus run write-back is 2d).
import { useWorkspace } from '../workspace';
const w = useWorkspace();
const fields: { key: string; label: string }[] = [
	{ key: 'sample_name', label: 'Sample name' },
	{ key: 'sample_code', label: 'Sample code' },
	{ key: 'operation', label: 'Operation' },
	{ key: 'op_type', label: 'Operation type' },
	{ key: 'insert', label: 'Insert' },
	{ key: 'edge_id', label: 'Edge ID' },
	{ key: 'tool', label: 'Tool' },
	{ key: 'machine', label: 'Machine' },
	{ key: 'coolant', label: 'Coolant' },
];
</script>

<template>
	<div class="meta">
		<label v-for="f in fields" :key="f.key">{{ f.label }}
			<input v-model="w.meta[f.key]" :disabled="w.locked.value" />
		</label>
		<label class="wide">Notes
			<textarea v-model="w.meta.notes" rows="2" :disabled="w.locked.value"></textarea>
		</label>
	</div>
</template>

<style scoped>
.meta { display: grid; grid-template-columns: 1fr 1fr; gap: 0 10px; }
label { display: block; font-size: 11.5px; color: var(--text-dim); margin-bottom: 8px; }
label.wide { grid-column: 1 / -1; }
input, textarea { display: block; width: 100%; margin-top: 3px; padding: 7px 9px; font-size: 13px; color: var(--text); background: rgba(0,0,0,0.25); border: 1px solid var(--border); border-radius: 7px; outline: none; font-family: inherit; resize: vertical; }
input:focus, textarea:focus { border-color: var(--accent); }
input:disabled, textarea:disabled { opacity: 0.55; }
</style>
