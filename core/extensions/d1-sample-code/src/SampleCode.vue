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
					v-tooltip="'Assign the next available number (renumber)'"
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

const props = defineProps<{ value: string | null; primaryKey?: string | number | null }>();
const emit = defineEmits<{ (e: 'input', value: string | null): void }>();

const values = inject<Ref<Record<string, any>>>('values', ref({}));
const api = useApi();

const parts = ref<string>('');

// Was this component opened on an already-saved item that had a code? Captured
// once at setup so an async value load can't flip it later.
const openedWithCode = /^\d+-/.test(props.value ?? '');

// An EXISTING item: it has a real primary key ('+' / null means a new, unsaved
// item). We pause all auto-generation for existing items so merely opening or
// editing one can never recalculate/renumber its code — only the autorenew
// button (force) may. New items still auto-build as you fill alloy/method/date.
function isExistingItem(): boolean {
	const pk = props.primaryKey;
	return (pk !== undefined && pk !== null && pk !== '+') || openedWithCode;
}

function onType(v: string | null) {
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

// Next FREE sequence number = max leading integer across OTHER samples + 1.
// Excludes this sample's own current code, so re-running is idempotent and can
// never bump the sample's own number.
async function nextSequence(): Promise<number> {
	try {
		const own = props.value ?? '';
		const res = await api.get('/items/physical_samples', {
			params: { fields: ['sample_code'], limit: -1 },
		});
		let max = 0;
		for (const r of res?.data?.data ?? []) {
			if ((r.sample_code ?? '') === own) continue; // never count ourselves
			const m = /^(\d+)-/.exec(r.sample_code ?? '');
			if (m) max = Math.max(max, parseInt(m[1], 10));
		}
		return max + 1;
	} catch {
		return 1;
	}
}

// `force` = deliberately assign a fresh next number (the autorenew button).
// Otherwise the sequence number is PRESERVED from the current code — only the
// alloy/method/date parts regenerate — so editing a sample never renumbers it.
async function rebuild(force = false) {
	// Pause auto-generation for existing items (only the renumber button forces it).
	if (!force && isExistingItem()) return;
	const v = values.value ?? {};
	const alloy = v.material_id ? await lookup('materials', v.material_id, 'alloy_code') : null;
	const method = v.primary_method_id ? await lookup('manufacturing_methods', v.primary_method_id, 'method_code') : null;
	if (!alloy || !method) {
		parts.value = '';
		return;
	}
	const d = v.manufactured_date ? new Date(v.manufactured_date) : new Date();

	const existing = /^(\d+)-/.exec(props.value ?? '');
	// A hand-typed code with no leading number is left untouched (unless forced).
	if (props.value && !existing && !force) return;
	const seq = existing && !force ? parseInt(existing[1], 10) : await nextSequence();

	const code = `${seq}-${alloy}-${method}-${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
	parts.value = `${seq} · ${alloy} · ${method} · ${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
	if (code !== props.value) emit('input', code); // avoid marking the form dirty on open
}

// Regenerate only on a genuine user change to the inputs — NOT on open (no
// `immediate`), and never for an existing item (rebuild() pauses on those).
// This double-guards against the code being recalculated when a saved sample
// is merely opened.
watch(
	() => [values.value?.material_id, values.value?.primary_method_id, values.value?.manufactured_date],
	() => rebuild(false),
);
</script>

<style scoped>
.d1-sample-code { width: 100%; }
.hint { margin-top: 4px; font-size: 12px; color: var(--theme--primary, #1565c0); }
.hint .muted { color: var(--theme--foreground-subdued, #999); font-style: italic; }
</style>
