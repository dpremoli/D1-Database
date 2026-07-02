<template>
	<div class="d1-process-category">
		<span v-if="label" class="chip">{{ label }}</span>
		<span v-else class="muted">— set automatically from the Manufacturing Method —</span>
	</div>
</template>

<script setup lang="ts">
import { inject, computed, watch, ref, type Ref } from 'vue';
import { useApi } from '@directus/extensions-sdk';

const props = defineProps<{ value: string | null }>();
const emit = defineEmits<{ (e: 'input', value: string | null): void }>();

// Directus injects the live form values as a Vue Ref.
const values = inject<Ref<Record<string, any>>>('values', ref({}));
const api = useApi();

// Manufacturing method code → process category.
const CODE_TO_CAT: Record<string, string> = {
	MC: 'machining', MM: 'machining', MC2: 'machining', MEDM: 'machining',
	MCO: 'machining', MX: 'machining', MS: 'machining', MT: 'machining',
	MF: 'sintering', MHIP: 'sintering',
	HT: 'heat_treatment',
	MO: 'deformation', MR: 'deformation',
	MAM: 'additive', MW: 'additive', MAE: 'additive',
	MP: 'sample_prep',
};
const CAT_LABEL: Record<string, string> = {
	machining: 'Machining', sintering: 'Sintering (FAST / HIP)',
	heat_treatment: 'Heat Treatment', deformation: 'Deformation', additive: 'Additive',
	sample_prep: 'Sample Preparation',
};

const current = ref<string | null>(props.value ?? null);
const label = computed(() => (current.value ? CAT_LABEL[current.value] ?? current.value : null));

const methodId = computed<string | null>(() => values.value?.method_id ?? null);

watch(
	methodId,
	async (id) => {
		if (!id) {
			if (current.value !== null) {
				current.value = null;
				emit('input', null);
			}
			return;
		}
		try {
			const res = await api.get(`/items/manufacturing_methods/${id}`, {
				params: { fields: ['method_code'] },
			});
			const code: string | undefined = res?.data?.data?.method_code;
			const cat = code ? CODE_TO_CAT[code] ?? null : null;
			if (cat !== current.value) {
				current.value = cat;
				emit('input', cat);
			}
		} catch {
			/* leave the existing value untouched on lookup failure */
		}
	},
	{ immediate: true },
);
</script>

<style scoped>
.d1-process-category {
	display: flex;
	align-items: center;
	min-height: var(--theme--form--field--input--height, 60px);
}
.chip {
	background: var(--theme--primary-background, #e3f2fd);
	color: var(--theme--primary, #1565c0);
	font-weight: 600;
	padding: 4px 12px;
	border-radius: 16px;
	font-size: 14px;
}
.muted {
	color: var(--theme--foreground-subdued, #999);
	font-style: italic;
	font-size: 13px;
}
</style>
