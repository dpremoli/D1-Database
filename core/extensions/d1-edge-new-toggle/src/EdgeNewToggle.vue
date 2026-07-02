<template>
	<div class="d1-edge-new-toggle">
		<v-checkbox
			:model-value="value === true"
			:label="value ? 'Yes — a new (unused) edge' : 'No — a previously used edge'"
			block
			@update:model-value="onToggle"
		/>
		<small v-if="inherited" class="hint">Inherited from the selected insert edge — toggle to override.</small>
	</div>
</template>

<script setup lang="ts">
import { inject, ref, computed, watch, type Ref } from 'vue';
import { useApi } from '@directus/extensions-sdk';

const props = defineProps<{ value: boolean | null }>();
const emit = defineEmits<{ (e: 'input', value: boolean | null): void }>();

const values = inject<Ref<Record<string, any>>>('values', ref({}));
const api = useApi();

const inherited = ref(false);
const insertEdgeId = computed<string | null>(() => values.value?.insert_edge_id ?? null);

// Only react to an actual edge change (immediate:false) so existing records keep
// their stored value on load; picking/changing the edge re-inherits.
watch(insertEdgeId, async (id) => {
	if (!id) {
		inherited.value = false;
		return;
	}
	try {
		const res = await api.get(`/items/insert_edges/${id}`, { params: { fields: ['is_used'] } });
		const isUsed: boolean = res?.data?.data?.is_used === true;
		// A fresh (unused) edge means a NEW edge is being used → new_edge = !is_used.
		const newEdge = !isUsed;
		inherited.value = true;
		if (newEdge !== props.value) emit('input', newEdge);
	} catch {
		/* leave the current value untouched on lookup failure */
	}
});

function onToggle(checked: boolean) {
	inherited.value = false; // manual override
	emit('input', checked);
}
</script>

<style scoped>
.d1-edge-new-toggle { width: 100%; }
.hint {
	display: block;
	margin-top: 4px;
	font-size: 12px;
	color: var(--theme--foreground-subdued, #999);
	font-style: italic;
}
</style>
