<template>
	<div class="d1-material-inherit">
		<v-select
			:items="items"
			:model-value="value"
			placeholder="Select a material / alloy…"
			show-deselect
			:search="true"
			@update:model-value="emit('input', $event)"
		/>
		<small v-if="inheritedFrom" class="hint">Inherited from input sample — override by selecting another</small>
	</div>
</template>

<script setup lang="ts">
import { inject, ref, computed, watch, type Ref } from 'vue';
import { useApi } from '@directus/extensions-sdk';

const props = defineProps<{ value: string | null }>();
const emit = defineEmits<{ (e: 'input', value: string | null): void }>();

const values = inject<Ref<Record<string, any>>>('values', ref({}));
const api = useApi();

const items = ref<{ text: string; value: string }[]>([]);
const inheritedFrom = ref<string | null>(null);

// Load all materials once for the dropdown.
api.get('/items/materials', {
	params: {
		fields: ['material_id', 'common_name', 'alloy_code'],
		sort: 'alloy_code',
		limit: -1,
	},
}).then((res: any) => {
	items.value = (res?.data?.data ?? []).map((m: any) => ({
		text: `${m.common_name ?? ''} (${m.alloy_code ?? '?'})`.trim(),
		value: m.material_id,
	}));
}).catch(() => {});

const sampleId = computed<string | null>(() => values.value?.sample_id ?? null);

// When sample changes and no material is set yet, inherit from the sample.
watch(sampleId, async (id) => {
	if (!id) {
		inheritedFrom.value = null;
		return;
	}
	if (props.value) return; // user already picked one; don't override
	try {
		const res = await api.get(`/items/physical_samples/${id}`, {
			params: { fields: ['material_id'] },
		});
		const mat: string | null = res?.data?.data?.material_id ?? null;
		if (mat && !props.value) {
			inheritedFrom.value = id;
			emit('input', mat);
		}
	} catch {}
}, { immediate: true });
</script>

<style scoped>
.d1-material-inherit { width: 100%; }
.hint {
	display: block;
	margin-top: 4px;
	font-size: 12px;
	color: var(--theme--foreground-subdued, #999);
	font-style: italic;
}
</style>
