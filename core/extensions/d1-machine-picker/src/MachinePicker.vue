<template>
	<div class="d1-machine-picker">
		<v-notice v-if="!category" type="info">
			Pick the {{ categoryFieldLabel }} first — the machine list filters to capable equipment.
		</v-notice>
		<v-select
			v-else
			:items="items"
			:model-value="value"
			:placeholder="items.length ? 'Select a machine…' : 'No capable machines'"
			show-deselect
			@update:model-value="emit('input', $event)"
		/>
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

const items = ref<{ text: string; value: string }[]>([]);

watch(
	category,
	async (cat) => {
		if (!cat) {
			items.value = [];
			return;
		}
		try {
			const res = await api.get('/items/equipment', {
				params: {
					fields: ['equipment_id', 'equipment_name'],
					filter: { capabilities: { _contains: cat } },
					sort: 'equipment_name',
					limit: -1,
				},
			});
			items.value = (res?.data?.data ?? []).map((e: any) => ({
				text: e.equipment_name,
				value: e.equipment_id,
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
</style>
