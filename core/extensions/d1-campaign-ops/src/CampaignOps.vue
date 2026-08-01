<script setup lang="ts">
/*
 * Manage a campaign's operations with a type-aware add search. The available-ops
 * search is pre-filtered by the campaign's type (a Machining Trial only surfaces
 * machining operations), directly addressing "pre-filter available operations based
 * on the campaign type". Add/remove sets the operation's campaign_id.
 */
import { computed, inject, onMounted, ref, watch } from 'vue';
import { useApi } from '@directus/extensions-sdk';

const props = defineProps<{ primaryKey?: string | number | null }>();
const api = useApi();

// The live form values (so we react to the campaign_type dropdown without a save).
const values = inject<any>('values', ref({}));
const campaignType = computed(() => values.value?.campaign_type as string | undefined);

// Which manufacturing process_category each campaign type should offer. null = no
// category restriction (types that don't select manufacturing operations).
const CATEGORY_FOR_TYPE: Record<string, string | null> = {
	machining_trial: 'machining',
	testing_campaign: null,
	imaging_analysis: null,
};
const category = computed(() => (campaignType.value ? CATEGORY_FOR_TYPE[campaignType.value] ?? null : null));

const isNew = computed(() => props.primaryKey == null || props.primaryKey === '+');

const linked = ref<any[]>([]);
async function loadLinked() {
	if (isNew.value) { linked.value = []; return; }
	const res = await api.get('/items/manufacturing_operations', {
		params: { filter: { campaign_id: { _eq: props.primaryKey } }, fields: ['operation_id', 'pass_code', 'process_category'], sort: ['pass_code'], limit: -1 },
	});
	linked.value = res.data?.data ?? [];
}
onMounted(loadLinked);
watch(() => props.primaryKey, loadLinked);

// ---- add search (type-filtered) ----
const search = ref('');
const results = ref<any[]>([]);
const searching = ref(false);
let timer: any;
watch(search, () => { clearTimeout(timer); timer = setTimeout(runSearch, 250); });
watch(category, runSearch);

async function runSearch() {
	if (isNew.value) return;
	searching.value = true;
	try {
		const filter: any = { _and: [{ campaign_id: { _null: true } }] };
		if (category.value) filter._and.push({ process_category: { _eq: category.value } });
		if (search.value.trim()) filter._and.push({ pass_code: { _icontains: search.value.trim() } });
		const res = await api.get('/items/manufacturing_operations', {
			params: { filter, fields: ['operation_id', 'pass_code', 'process_category', 'sample_id.sample_code'], sort: ['pass_code'], limit: 25 },
		});
		results.value = res.data?.data ?? [];
	} catch { results.value = []; } finally { searching.value = false; }
}

async function add(op: any) {
	await api.patch(`/items/manufacturing_operations/${op.operation_id}`, { campaign_id: props.primaryKey });
	results.value = results.value.filter((r) => r.operation_id !== op.operation_id);
	await loadLinked();
}
async function remove(op: any) {
	await api.patch(`/items/manufacturing_operations/${op.operation_id}`, { campaign_id: null });
	await loadLinked();
	runSearch();
}
</script>

<template>
	<div class="co">
		<div v-if="isNew" class="co-msg">Save the campaign first, then add operations here.</div>
		<template v-else>
			<div class="co-linked">
				<div v-for="op in linked" :key="op.operation_id" class="co-chip">
					<span class="mono">{{ op.pass_code || '—' }}</span>
					<button class="x" title="Remove from campaign" @click="remove(op)"><v-icon name="close" x-small /></button>
				</div>
				<span v-if="!linked.length" class="co-empty">No operations in this campaign yet.</span>
			</div>

			<div class="co-add">
				<div class="co-add-head">
					<v-icon name="add" x-small />
					<input v-model="search" class="co-search" :placeholder="category ? `Add ${category} operations…` : 'Add operations…'" />
					<span v-if="category" class="co-filter">filtered: {{ category }}</span>
				</div>
				<div v-if="searching" class="co-msg sm"><v-progress-circular indeterminate x-small /> searching…</div>
				<div v-else-if="results.length" class="co-results">
					<button v-for="op in results" :key="op.operation_id" class="co-result" @click="add(op)">
						<span class="mono">{{ op.pass_code || '—' }}</span>
						<span class="co-sub">{{ op.sample_id?.sample_code || op.process_category }}</span>
						<v-icon name="add_circle" x-small />
					</button>
				</div>
				<div v-else-if="search" class="co-msg sm">No unassigned {{ category || '' }} operations match.</div>
			</div>
		</template>
	</div>
</template>

<style scoped>
.co { font-size: 13px; }
.co-msg { color: var(--theme--foreground-subdued, #6b7684); padding: 8px 2px; display: flex; align-items: center; gap: 6px; } .co-msg.sm { font-size: 12px; padding: 5px 2px; }
.co-linked { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.co-chip { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--theme--border-color-subdued, #e7ebf0); background: var(--theme--background-subdued, #f7f9fb); border-radius: 8px; padding: 4px 6px 4px 10px; }
.co-chip .x { border: 0; background: transparent; cursor: pointer; color: var(--theme--foreground-subdued, #94a3b8); border-radius: 5px; display: inline-flex; }
.co-chip .x:hover { color: #b91c1c; background: color-mix(in srgb, #b91c1c 10%, transparent); }
.co-empty { color: var(--theme--foreground-subdued, #98a2b3); font-size: 12px; }
.co-add { border: 1px dashed var(--theme--border-color, #d1d9e6); border-radius: 10px; padding: 8px 10px; }
.co-add-head { display: flex; align-items: center; gap: 6px; }
.co-search { flex: 1 1 auto; border: 0; background: transparent; font: inherit; font-size: 13px; outline: none; color: var(--theme--foreground, #1e293b); }
.co-filter { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; color: #2563eb; background: color-mix(in srgb, #2563eb 10%, transparent); padding: 2px 8px; border-radius: 99px; }
.co-results { display: flex; flex-direction: column; gap: 3px; margin-top: 8px; max-height: 260px; overflow-y: auto; }
.co-result { display: flex; align-items: center; gap: 8px; text-align: left; border: 1px solid var(--theme--border-color-subdued, #eef1f5); background: var(--theme--background, #fff); border-radius: 8px; padding: 5px 10px; cursor: pointer; }
.co-result:hover { border-color: #2563eb; background: color-mix(in srgb, #2563eb 5%, transparent); }
.co-result .co-sub { color: var(--theme--foreground-subdued, #6b7684); font-size: 11px; margin-left: auto; margin-right: 6px; }
.mono { font-family: var(--theme--fonts--monospace--font-family, 'SF Mono', Menlo, monospace); font-weight: 650; }
</style>
