<script setup lang="ts">
// A single numeric cut-parameter card: big value + unit, small caps label below. Two modes off the
// same markup — `editable` wraps a real number input (styled to read as plain text until focused),
// used for the sim/nidaq recording config; without it, the card is a plain readout, used for a
// picked replay cut's actual parameters. One component so both stay visually identical.
import { computed } from 'vue';
withDefaults(defineProps<{
	label: string;
	unit?: string;
	editable?: boolean;
	disabled?: boolean;
	step?: string | number;
	title?: string;
	/** #46: flags the field immediately (an info icon + the tile's title tooltip) when its current
	 *  value is known to be out of bounds -- e.g. a sample rate the assigned NI-DAQ hardware can't
	 *  actually deliver -- rather than only surfacing as a raw acquisition-time error once a
	 *  recording has already started. */
	invalid?: boolean;
}>(), { editable: false, step: 'any' });
const model = defineModel<number | string>();
// Read-only values often arrive as floats decoded from a float32 wire/cache format (e.g. the D1LC
// header) round-tripped through JS's double precision — 0.05 comes back as 0.05000000745058059.
// Round away that binary noise instead of showing it (and overflowing the tile).
const display = computed(() => {
	const v = model.value;
	if (typeof v === 'number' && Number.isFinite(v)) return Number(v.toPrecision(6));
	return v;
});
</script>

<template>
	<div class="stat-tile" :class="{ invalid }" :title="title">
		<div class="value">
			<input v-if="editable" type="number" :step="step" v-model.number="model" :disabled="disabled" />
			<span v-else class="value-text">{{ display }}</span>
			<span v-if="unit" class="unit">{{ unit }}</span>
			<span v-if="invalid" class="material-symbols-rounded warn-icon">info</span>
		</div>
		<div class="label">{{ label }}</div>
	</div>
</template>

<style scoped>
.stat-tile { padding: 10px 12px; background: rgba(255,255,255,0.03); border: 1px solid var(--border); border-radius: 10px; min-width: 0; overflow: hidden; }
.stat-tile.invalid { border-color: #fbbf24; background: rgba(251,191,36,0.08); }
.warn-icon { font-size: 15px; color: #fbbf24; margin-left: auto; }
.value { display: flex; align-items: baseline; gap: 5px; min-width: 0; }
.value input, .value-text { font-size: 16px; font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; min-width: 0; }
.value-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.value input { flex: 1; padding: 0; background: transparent; border: none; border-bottom: 1px dashed rgba(255,255,255,0.2); outline: none; }
.value input:focus { border-bottom-color: var(--accent); }
.value input:disabled { opacity: 0.6; }
.unit { font-size: 11px; font-weight: 600; color: var(--text-dim); flex-shrink: 0; }
/* Sentence case comes from the global label rule in styles.css; the size/weight here are the
   originals. */
.label { margin-top: 3px; font-size: 9.5px; font-weight: 700; letter-spacing: 0.07em; color: var(--text-dim); }
</style>
