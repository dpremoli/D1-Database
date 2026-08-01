<template>
	<div class="composition-bar">
		<!-- Unsaved record: no PK to query the junction yet -->
		<div v-if="!materialId" class="notice">Save the material to see its composition breakdown.</div>

		<div v-else-if="loading" class="notice">Loading composition…</div>

		<!-- No elements linked at all -->
		<div v-else-if="elements.length === 0" class="notice">
			No alloying elements recorded yet. Add elements above to build the breakdown.
		</div>

		<!-- Elements present but none have a weight % -->
		<div v-else-if="specifiedSum === 0" class="notice">
			<div class="chips">
				<span v-for="e in elements" :key="e.symbol" class="chip">{{ e.symbol }}</span>
			</div>
			<span class="hint">Add a weight % to each element (then save) to see the stacked breakdown.</span>
		</div>

		<!-- The stacked horizontal % bar -->
		<template v-else>
			<div class="bar" role="img" :aria-label="ariaLabel">
				<div
					v-for="seg in segments"
					:key="seg.key"
					class="seg"
					:style="{ width: seg.widthPct + '%', background: seg.color }"
					:title="seg.label + ' — ' + seg.pctLabel"
				>
					<span v-if="seg.widthPct >= 7" class="seg-label">{{ seg.symbol }}</span>
				</div>
			</div>

			<div class="legend">
				<span v-for="seg in segments" :key="'l-' + seg.key" class="legend-item">
					<span class="swatch" :style="{ background: seg.color }"></span>
					<b>{{ seg.label }}</b>&nbsp;{{ seg.pctLabel }}
				</span>
			</div>

			<div v-if="overspecified" class="warn">
				⚠ Specified elements sum to {{ specifiedSum.toFixed(1) }} wt% (over 100). Bar is shown normalised.
			</div>
		</template>
	</div>
</template>

<script setup lang="ts">
import { inject, computed, ref, watch, type Ref } from 'vue';
import { useApi } from '@directus/extensions-sdk';

// Directus injects the live form values as a Vue Ref.
const values = inject<Ref<Record<string, any>>>('values', ref({}));
const v = computed(() => values.value ?? {});
const api = useApi();

// materials PK column is `material_id`.
const materialId = computed(() => v.value.material_id ?? null);

const num = (x: any): number | null => {
	const n = typeof x === 'string' ? parseFloat(x) : x;
	return typeof n === 'number' && !Number.isNaN(n) ? n : null;
};

// Distinct, colour-blind-friendly-ish palette cycled by element index.
const PALETTE = [
	'#1565C0', '#EF6C00', '#2E7D32', '#6A1B9A', '#C62828', '#00838F',
	'#F9A825', '#4E342E', '#AD1457', '#283593', '#558B2F', '#00695C',
];
const BALANCE_COLOR = '#B0BEC5';

type Elem = { symbol: string; wt: number | null };
const elements = ref<Elem[]>([]);
const loading = ref(false);

async function load(id: string | null) {
	if (!id) { elements.value = []; return; }
	loading.value = true;
	try {
		const res = await api.get('/items/material_alloying_elements', {
			params: {
				filter: { material_id: { _eq: id } },
				fields: ['symbol', 'weight_percent'],
				limit: -1,
			},
		});
		const rows = (res?.data?.data ?? []) as Array<Record<string, any>>;
		elements.value = rows
			.map((r) => ({ symbol: String(r.symbol ?? '?'), wt: num(r.weight_percent) }))
			// heaviest first; unspecified (null) sink to the bottom
			.sort((a, b) => (b.wt ?? -1) - (a.wt ?? -1));
	} catch {
		elements.value = [];
	} finally {
		loading.value = false;
	}
}

// Reload on material change and whenever the linked-element set changes
// (add/remove/save of the M2M field re-triggers the fetch).
watch(materialId, (id) => load(id), { immediate: true });
watch(
	() => {
		const a = v.value.alloying_elements;
		return Array.isArray(a) ? a.length : a;
	},
	() => load(materialId.value),
);

const specifiedSum = computed(() =>
	elements.value.reduce((s, e) => s + (e.wt ?? 0), 0),
);
const overspecified = computed(() => specifiedSum.value > 100.0001);

const segments = computed(() => {
	const sum = specifiedSum.value;
	if (sum <= 0) return [];
	// Normalise to 100 if over-specified; otherwise real wt% with a balance segment.
	const scale = overspecified.value ? 100 / sum : 1;
	const segs = elements.value
		.filter((e) => (e.wt ?? 0) > 0)
		.map((e, i) => {
			const wt = (e.wt as number);
			return {
				key: e.symbol + i,
				symbol: e.symbol,
				label: e.symbol,
				widthPct: wt * scale,
				pctLabel: wt.toFixed(wt < 1 ? 2 : 1) + ' wt%',
				color: PALETTE[i % PALETTE.length],
			};
		});
	// Balance (matrix / base element) fills the remainder to 100%.
	if (!overspecified.value && sum < 99.999) {
		segs.push({
			key: 'balance',
			symbol: 'Bal.',
			label: 'Balance (matrix)',
			widthPct: 100 - sum,
			pctLabel: (100 - sum).toFixed(1) + ' wt%',
			color: BALANCE_COLOR,
		});
	}
	return segs;
});

const ariaLabel = computed(() =>
	'Composition: ' + segments.value.map((s) => `${s.label} ${s.pctLabel}`).join(', '),
);
</script>

<style scoped>
.composition-bar {
	display: flex;
	flex-direction: column;
	gap: 10px;
	padding: 6px 0;
}

.bar {
	display: flex;
	width: 100%;
	height: 28px;
	border-radius: 6px;
	overflow: hidden;
	box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.08);
}

.seg {
	display: flex;
	align-items: center;
	justify-content: center;
	min-width: 2px;
	transition: width 0.25s ease;
}

.seg-label {
	font-size: 11px;
	font-weight: 600;
	color: #fff;
	text-shadow: 0 1px 1px rgba(0, 0, 0, 0.35);
	white-space: nowrap;
}

.legend {
	display: flex;
	flex-wrap: wrap;
	gap: 6px 14px;
	font-size: 12px;
	color: var(--foreground-normal, #333);
}

.legend-item {
	display: inline-flex;
	align-items: center;
	gap: 5px;
}

.swatch {
	width: 11px;
	height: 11px;
	border-radius: 3px;
	display: inline-block;
	box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.15);
}

.chips {
	display: flex;
	flex-wrap: wrap;
	gap: 6px;
	margin-bottom: 6px;
}

.chip {
	background: var(--background-subdued, #eef1f4);
	border-radius: 4px;
	padding: 2px 8px;
	font-size: 12px;
	font-weight: 600;
}

.notice,
.hint {
	color: var(--foreground-subdued, #888);
	font-style: italic;
	font-size: 13px;
}

.warn {
	color: var(--warning, #b26a00);
	font-size: 12px;
}
</style>
