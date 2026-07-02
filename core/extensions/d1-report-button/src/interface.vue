<script setup lang="ts">
import { computed } from 'vue';

const props = withDefaults(
	defineProps<{
		primaryKey?: string | number | null;
		collection?: string;
		label?: string;
		report?: string;
	}>(),
	{ label: 'Generate PDF', report: 'auto' },
);

// New (unsaved) items have primaryKey '+' — nothing to report yet.
const isNew = computed(() => props.primaryKey == null || props.primaryKey === '+');

const reportType = computed(() => {
	if (props.report && props.report !== 'auto') return props.report;
	return props.collection === 'manufacturing_operations' ? 'operation' : 'sample';
});

const url = computed(() => `/d1-report/${reportType.value}/${props.primaryKey}`);

function open() {
	if (!isNew.value) window.open(url.value, '_blank', 'noopener');
}
</script>

<template>
	<div class="d1-report-button">
		<v-button :disabled="isNew" @click="open">
			<v-icon name="picture_as_pdf" left />
			{{ label }}
		</v-button>
		<span v-if="isNew" class="hint">Save the record first to generate its PDF.</span>
	</div>
</template>

<style scoped>
.d1-report-button {
	display: flex;
	align-items: center;
	gap: 12px;
}
.hint {
	color: var(--theme--foreground-subdued, #6c7789);
	font-size: 13px;
	font-style: italic;
}
</style>
