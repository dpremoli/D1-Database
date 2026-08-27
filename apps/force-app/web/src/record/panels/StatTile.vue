<script setup lang="ts">
// A single numeric cut-parameter card: big value + unit, small caps label below. Two modes off the
// same markup — `editable` wraps a real number input (styled to read as plain text until focused),
// used for the sim/nidaq recording config; without it, the card is a plain readout, used for a
// picked replay cut's actual parameters. One component so both stay visually identical.
withDefaults(defineProps<{
	label: string;
	unit?: string;
	editable?: boolean;
	disabled?: boolean;
	step?: string | number;
	title?: string;
}>(), { editable: false, step: 'any' });
const model = defineModel<number | string>();
</script>

<template>
	<div class="stat-tile" :title="title">
		<div class="value">
			<input v-if="editable" type="number" :step="step" v-model.number="model" :disabled="disabled" />
			<span v-else class="value-text">{{ model }}</span>
			<span v-if="unit" class="unit">{{ unit }}</span>
		</div>
		<div class="label">{{ label }}</div>
	</div>
</template>

<style scoped>
.stat-tile { padding: 10px 12px; background: rgba(255,255,255,0.03); border: 1px solid var(--border); border-radius: 10px; min-width: 0; }
.value { display: flex; align-items: baseline; gap: 5px; }
.value input, .value-text { font-size: 16px; font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; min-width: 0; }
.value input { flex: 1; padding: 0; background: transparent; border: none; border-bottom: 1px dashed rgba(255,255,255,0.2); outline: none; }
.value input:focus { border-bottom-color: var(--accent); }
.value input:disabled { opacity: 0.6; }
.unit { font-size: 11px; font-weight: 600; color: var(--text-dim); flex-shrink: 0; }
.label { margin-top: 3px; font-size: 9.5px; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase; color: var(--text-dim); }
</style>
