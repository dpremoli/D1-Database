<template>
	<div class="d1-sample-code">
		<v-input
			:model-value="value"
			placeholder="Auto-built from alloy, method & date…"
			@update:model-value="onType"
		>
			<template #append>
				<v-icon
					name="autorenew"
					clickable
					v-tooltip="'Rebuild from alloy / method / date'"
					@click="rebuild(true)"
				/>
			</template>
		</v-input>
		<div class="hint">
			<span v-if="parts">{{ parts }}</span>
			<span v-else class="muted">Pick alloy + method to auto-build the code.</span>
		</div>
	</div>
</template>

<script setup lang="ts">
import { inject, ref, watch, type Ref } from 'vue';
import { useApi } from '@directus/extensions-sdk';

const props = defineProps<{ value: string | null }>();
const emit = defineEmits<{ (e: 'input', value: string | null): void }>();

const values = inject<Ref<Record<string, any>>>('values', ref({}));
const api = useApi();

const manuallyEdited = ref(!!props.value);
const parts = ref<string>('');

function onType(v: string | null) {
	manuallyEdited.value = true;
	emit('input', v);
}

async function lookup(collection: string, id: string, field: string): Promise<string | null> {
	try {
		const res = await api.get(`/items/${collection}/${id}`, { params: { fields: [field] } });
		return res?.data?.data?.[field] ?? null;
	} catch {
		return null;
	}
}

async function nextSequence(): Promise<number> {
	try {
		// Pull existing codes and take max leading integer + 1.
		const res = await api.get('/items/physical_samples', {
			params: { fields: ['sample_code'], limit: -1 },
		});
		let max = 0;
		for (const r of res?.data?.data ?? []) {
			const m = /^(\d+)-/.exec(r.sample_code ?? '');
			if (m) max = Math.max(max, parseInt(m[1], 10));
		}
		return max + 1;
	} catch {
		return 1;
	}
}

async function rebuild(force = false) {
	if (manuallyEdited.value && !force) return;
	const v = values.value ?? {};
	const alloy = v.material_id ? await lookup('materials', v.material_id, 'alloy_code') : null;
	const method = v.primary_method_id ? await lookup('manufacturing_methods', v.primary_method_id, 'method_code') : null;
	if (!alloy || !method) {
		parts.value = '';
		return;
	}
	const d = v.manufactured_date ? new Date(v.manufactured_date) : new Date();
	const seq = await nextSequence();
	const code = `${seq}-${alloy}-${method}-${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
	parts.value = `${seq} · ${alloy} · ${method} · ${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
	manuallyEdited.value = false;
	emit('input', code);
}

// Rebuild whenever the inputs change (unless the user has typed their own).
watch(
	() => [values.value?.material_id, values.value?.primary_method_id, values.value?.manufactured_date],
	() => rebuild(false),
	{ immediate: true },
);
</script>

<style scoped>
.d1-sample-code { width: 100%; }
.hint { margin-top: 4px; font-size: 12px; color: var(--theme--primary, #1565c0); }
.hint .muted { color: var(--theme--foreground-subdued, #999); font-style: italic; }
</style>
