<template>
	<div class="d1-machine-picker">
		<v-notice v-if="!category" type="info">
			Pick the {{ categoryFieldLabel }} first — the machine list filters to capable equipment.
		</v-notice>
		<template v-else>
			<!-- Tier 1: narrow by facility (optional). Mirrors Directus's grouped
			     dropdowns — pick a lab, then the machine list below narrows to it. -->
			<v-select
				v-if="facilityItems.length > 1"
				class="facility-select"
				:items="facilityItems"
				:model-value="facilityFilter"
				placeholder="All facilities"
				show-deselect
				@update:model-value="facilityFilter = $event"
			/>
			<!-- Tier 2: the machine, filtered by capability (always) and facility (if set). -->
			<v-select
				:items="visibleItems"
				:model-value="value"
				:placeholder="visibleItems.length ? 'Select a machine…' : 'No capable machines'"
				show-deselect
				@update:model-value="emit('input', $event)"
			/>
		</template>
	</div>
</template>

<script setup lang="ts">
import { inject, ref, computed, watch, type Ref } from 'vue';
import { useApi } from '@directus/extensions-sdk';

const props = defineProps<{ value: string | null; categoryField?: string }>();
const emit = defineEmits<{ (e: 'input', value: string | null): void }>();

const values = inject<Ref<Record<string, any>>>('values', ref({}));
const api = useApi();

const field = computed(() => props.categoryField || 'process_category');
const categoryFieldLabel = computed(() =>
	field.value === 'test_category' ? 'Test Type' : 'Manufacturing Method',
);
const category = computed<string | null>(() => values.value?.[field.value] ?? null);

type Machine = { text: string; value: string; facility: string | null; facilityName: string | null };
const items = ref<Machine[]>([]);
const facilityFilter = ref<string | null>(null);

// Distinct facilities among the capable machines, for the tier-1 dropdown.
const facilityItems = computed(() => {
	const seen = new Map<string, string>();
	for (const m of items.value) {
		if (m.facility && m.facilityName && !seen.has(m.facility)) seen.set(m.facility, m.facilityName);
	}
	return [...seen.entries()]
		.map(([value, text]) => ({ text, value }))
		.sort((a, b) => a.text.localeCompare(b.text));
});

// Machines shown in tier-2: capability-filtered, then facility-filtered if a
// facility is chosen. When no facility is chosen the facility name is appended so
// the flat list stays legible.
const visibleItems = computed(() => {
	const list = facilityFilter.value
		? items.value.filter((m) => m.facility === facilityFilter.value)
		: items.value;
	return list.map((m) => ({
		value: m.value,
		text: facilityFilter.value || !m.facilityName ? m.text : `${m.text} · ${m.facilityName}`,
	}));
});

watch(
	category,
	async (cat) => {
		facilityFilter.value = null;
		if (!cat) {
			items.value = [];
			return;
		}
		try {
			const res = await api.get('/items/equipment', {
				params: {
					fields: ['equipment_id', 'equipment_name', 'facility_id', 'facility_id.name'],
					filter: { capabilities: { _contains: cat } },
					sort: ['facility_id.name', 'equipment_name'],
					limit: -1,
				},
			});
			items.value = (res?.data?.data ?? []).map((e: any) => ({
				text: e.equipment_name,
				value: e.equipment_id,
				facility: typeof e.facility_id === 'object' ? e.facility_id?.id ?? null : e.facility_id ?? null,
				facilityName: typeof e.facility_id === 'object' ? e.facility_id?.name ?? null : null,
			}));
		} catch {
			items.value = [];
		}
	},
	{ immediate: true },
);
</script>

<style scoped>
.d1-machine-picker { width: 100%; }
.facility-select { margin-bottom: 8px; }
</style>
