<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useApi } from '@directus/extensions-sdk';
import { useRouter } from 'vue-router';

const props = withDefaults(
	defineProps<{
		primaryKey?: string | number | null;
		collection?: string;
		label?: string;
		report?: string;
	}>(),
	{ label: 'Generate PDF', report: 'auto' },
);

const api = useApi();
const router = useRouter();

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

// "View Force Analysis" — only offered for a saved machining_operations record
// that already has a processed (status='done') machining_force_analysis row.
const hasForceAnalysis = ref(false);
async function checkForceAnalysis() {
	hasForceAnalysis.value = false;
	if (isNew.value || props.collection !== 'manufacturing_operations') return;
	try {
		const res = await api.get('/items/machining_force_analysis', {
			params: {
				filter: { operation_id: { _eq: props.primaryKey }, status: { _eq: 'done' } },
				limit: 1,
				fields: ['id'],
			},
		});
		hasForceAnalysis.value = (res.data?.data ?? []).length > 0;
	} catch {
		hasForceAnalysis.value = false;
	}
}
// "View FAST Analysis" — for a saved sintering operation with an imported trace.
const hasFastRun = ref(false);
async function checkFastRun() {
	hasFastRun.value = false;
	if (isNew.value || props.collection !== 'manufacturing_operations') return;
	try {
		const res = await api.get('/items/fast_run_data', {
			params: {
				filter: { operation_id: { _eq: props.primaryKey }, status: { _eq: 'done' } },
				limit: 1, fields: ['id'],
			},
		});
		hasFastRun.value = (res.data?.data ?? []).length > 0;
	} catch {
		hasFastRun.value = false;
	}
}

watch(() => [props.collection, props.primaryKey], () => { checkForceAnalysis(); checkFastRun(); }, { immediate: true });

function openForceAnalysis() {
	router.push(`/d1-force-dashboard?operation=${props.primaryKey}`);
}
function openFastAnalysis() {
	router.push(`/d1-fast-dashboard?operation=${props.primaryKey}`);
}
</script>

<template>
	<!-- Only offered once the record exists (nothing to report on a brand-new item). -->
	<div v-if="!isNew" class="d1-report-button">
		<v-button @click="open">
			<v-icon name="picture_as_pdf" left />
			{{ label }}
		</v-button>
		<v-button v-if="hasForceAnalysis" secondary @click="openForceAnalysis">
			<v-icon name="insights" left />
			View Force Analysis
		</v-button>
		<v-button v-if="hasFastRun" secondary @click="openFastAnalysis">
			<v-icon name="whatshot" left />
			View FAST Analysis
		</v-button>
	</div>
</template>

<style scoped>
.d1-report-button {
	display: flex;
	align-items: center;
	flex-wrap: wrap;
	gap: 10px;
	max-width: 100%;
}
.d1-report-button :deep(.v-button) { max-width: 100%; }
.d1-report-button :deep(.v-button .button) { white-space: normal; height: auto; min-height: 44px; padding: 8px 14px; }
.hint {
	color: var(--theme--foreground-subdued, #6c7789);
	font-size: 13px;
	font-style: italic;
}
</style>
