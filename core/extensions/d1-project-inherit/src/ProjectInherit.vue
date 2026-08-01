<template>
	<div class="d1-project-inherit">
		<v-select
			:items="items"
			:model-value="value"
			placeholder="Select a project…"
			show-deselect
			:search="true"
			@update:model-value="emit('input', $event)"
		/>
		<small v-if="inherited" class="hint">Inherited from campaign — override by selecting another</small>
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
const inherited = ref(false);

// Load all projects once for the dropdown.
api.get('/items/projects', {
	params: { fields: ['project_id', 'project_code', 'project_name'], sort: 'project_code', limit: -1 },
}).then((res: any) => {
	items.value = (res?.data?.data ?? []).map((p: any) => ({
		text: `${p.project_code ?? ''} – ${p.project_name ?? ''}`.trim(),
		value: p.project_id,
	}));
}).catch(() => {});

const campaignId = computed<string | null>(() => values.value?.campaign_id ?? null);

// When the campaign changes and no project is set yet, inherit the campaign's project.
watch(campaignId, async (id) => {
	if (!id) {
		inherited.value = false;
		return;
	}
	if (props.value) return; // explicit choice wins
	try {
		const res = await api.get(`/items/campaigns/${id}`, { params: { fields: ['project_id'] } });
		const proj: string | null = res?.data?.data?.project_id ?? null;
		if (proj && !props.value) {
			inherited.value = true;
			emit('input', proj);
		}
	} catch {}
}, { immediate: true });
</script>

<style scoped>
.d1-project-inherit { width: 100%; }
.hint {
	display: block;
	margin-top: 4px;
	font-size: 12px;
	color: var(--theme--foreground-subdued, #999);
	font-style: italic;
}
</style>
