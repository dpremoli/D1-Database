<template>
	<div class="d1-operation-code">
		<v-input
			:model-value="value"
			placeholder="auto-generated from the fields below…"
			@update:model-value="onType"
		>
			<template #append>
				<v-icon
					v-tooltip="manual ? 'Regenerate from fields' : 'Auto-generated'"
					:name="manual ? 'refresh' : 'auto_fix_high'"
					:clickable="manual"
					:class="{ active: !manual }"
					@click="regenerate"
				/>
			</template>
		</v-input>
		<small class="hint">
			{{ manual ? 'Manual override — click ↻ to regenerate.' : 'Auto-generated; type to override.' }}
		</small>
	</div>
</template>

<script setup lang="ts">
import { inject, ref, computed, watch, type Ref } from 'vue';
import { useApi } from '@directus/extensions-sdk';

const props = defineProps<{ value: string | null; primaryKey?: string | number | null }>();
const emit = defineEmits<{ (e: 'input', value: string | null): void }>();

const values = inject<Ref<Record<string, any>>>('values', ref({}));
const api = useApi();

// Existing records arrive with a value already set — never auto-clobber those.
// `value` can populate a tick after mount, so also key off the primary key: a
// real id (not '+') means an existing record we must never dirty on open.
const isExistingItem = () => props.primaryKey != null && props.primaryKey !== '+';
const manual = ref<boolean>(!!props.value || isExistingItem());

// --- resolve the input sample's code from sample_id ---
const sampleCode = ref<string | null>(null);
let lastSampleId: string | null = null;
const sampleId = computed<string | null>(() => values.value?.sample_id ?? null);
watch(
	sampleId,
	async (id) => {
		if (id === lastSampleId) return;
		lastSampleId = id;
		if (!id) {
			sampleCode.value = null;
			return;
		}
		try {
			const res = await api.get(`/items/physical_samples/${id}`, { params: { fields: ['sample_code'] } });
			sampleCode.value = res?.data?.data?.sample_code ?? null;
		} catch {
			sampleCode.value = null;
		}
	},
	{ immediate: true },
);

// Render a number without trailing-zero noise: 80 → "80", 0.05 → "0.05".
function num(v: unknown): string {
	if (v === null || v === undefined || v === '') return '';
	const n = Number(v);
	if (Number.isNaN(n)) return '';
	return String(parseFloat(n.toPrecision(6)));
}

// DD-MM-YY for the sintering code (FAST ops carry no sample, so the date + a global
// counter are what make the code unique). Empty when no date is set yet.
function dateCode(v: unknown): string {
	if (!v) return '';
	const d = new Date(v as string);
	if (Number.isNaN(d.getTime())) return '';
	const p = (x: number) => String(x).padStart(2, '0');
	return `${p(d.getDate())}-${p(d.getMonth() + 1)}-${String(d.getFullYear()).slice(-2)}`;
}

// Global running counter for a NEW sintering op — the next MF number after all
// existing ones (mirrors the DD-MM-YY-MF{n} scheme the backfill applied). Fetched
// once when the form is a new sintering record; null → fall back to the sequence.
const sinterSeq = ref<number | null>(null);
watch(
	() => values.value?.process_category,
	async (cat) => {
		if (cat !== 'sintering' || isExistingItem() || sinterSeq.value != null) return;
		try {
			const res = await api.get('/items/manufacturing_operations', {
				params: { filter: { process_category: { _eq: 'sintering' } }, aggregate: { count: '*' } },
			});
			const c = Number(res?.data?.data?.[0]?.count ?? 0);
			sinterSeq.value = (Number.isFinite(c) ? c : 0) + 1;
		} catch { sinterSeq.value = null; }
	},
	{ immediate: true },
);

// Abbreviation maps for the typed dropdowns.
const HT_TYPE: Record<string, string> = {
	anneal: 'A', solution_treat: 'S', age: 'AG', quench: 'Q',
	temper: 'T', stress_relieve: 'SR', normalise: 'N', other: 'X',
};
const HT_COOL: Record<string, string> = {
	furnace: 'FC', air: 'AC', water_quench: 'WQ', oil_quench: 'OQ', forced_air: 'FA', other: 'X',
};
const DEFORM_TOKEN: Record<string, string> = {
	rolling: 'DR', forging: 'DF', extrusion: 'DE', drawing: 'DD', other: 'DX',
};

// Compose the parameter-keyed code per process category:
//   base = {sample}-{op token};  then -{param}_{param}…  (only the variables that are set)
const autoCode = computed<string>(() => {
	const v = values.value ?? {};
	const sample = sampleCode.value ?? '';
	const cat = (v.process_category ?? '') as string;

	// Per-sample sequence number — the unique identifier every operation carries, so
	// two ops on the same sample never collide even with identical parameters. For
	// machining this is the facing/roughing pass number; for other methods it's just
	// the Nth operation on the sample.
	const seq = v.operation_sequence;
	const seqStr = seq === '' || seq === null || seq === undefined ? '' : String(seq);

	let token = '';
	let parts: string[] = [];

	if (cat === 'machining') {
		token = `${v.machining_operation_subtype ?? ''}${seqStr}`;
		parts = [
			num(v.machining_cutting_speed_m_per_min) && `${num(v.machining_cutting_speed_m_per_min)}MPM`,
			num(v.machining_feed_mm_per_rev) && `${num(v.machining_feed_mm_per_rev)}feed`,
			num(v.machining_axial_depth_of_cut_mm) && `${num(v.machining_axial_depth_of_cut_mm)}DoC`,
		].filter(Boolean) as string[];
	} else if (cat === 'sintering') {
		// FAST/sintering ops usually have no sample link, so uniqueness comes from the
		// date + a global counter:  DD-MM-YY-MF{NNNN}-{params}  (matches the backfill).
		const dcode = dateCode(v.operation_date);
		const nStr = sinterSeq.value != null ? String(sinterSeq.value) : seqStr;
		const mf = `MF${nStr}`;
		const sparams = [
			num(v.sintering_max_temp_celsius) && `${num(v.sintering_max_temp_celsius)}C`,
			num(v.sintering_max_force_kn) && `${num(v.sintering_max_force_kn)}kN`,
			num(v.sintering_mould_diameter_mm) && `${num(v.sintering_mould_diameter_mm)}dia`,
		].filter(Boolean).join('_');
		return [dcode, mf, sparams].filter(Boolean).join('-');
	} else if (cat === 'heat_treatment') {
		token = `HT${HT_TYPE[v.ht_treatment_type] ?? ''}${seqStr}`;
		parts = [
			num(v.ht_peak_temp_celsius) && `${num(v.ht_peak_temp_celsius)}C`,
			num(v.ht_hold_time_min) && `${num(v.ht_hold_time_min)}min`,
			HT_COOL[v.ht_cooling_method],
		].filter(Boolean) as string[];
	} else if (cat === 'deformation') {
		token = `${DEFORM_TOKEN[v.deform_deformation_type] ?? 'D'}${seqStr}`;
		parts = [
			num(v.deform_deformation_temp_celsius) && `${num(v.deform_deformation_temp_celsius)}C`,
			num(v.deform_total_reduction_pct) && `${num(v.deform_total_reduction_pct)}pct`,
			num(v.deform_pass_count) && `${num(v.deform_pass_count)}p`,
		].filter(Boolean) as string[];
	} else if (cat === 'additive') {
		token = `${v.am_process_variant ?? 'AM'}${seqStr}`;
		parts = [
			num(v.am_laser_power_w) && `${num(v.am_laser_power_w)}W`,
			num(v.am_scan_speed_mm_per_s) && `${num(v.am_scan_speed_mm_per_s)}mmps`,
			num(v.am_layer_thickness_mm) && `${num(v.am_layer_thickness_mm)}mm`,
		].filter(Boolean) as string[];
	} else {
		return seqStr ? `${sample}-${seqStr}` : sample; // unknown category — sample + seq
	}

	let code = sample;
	if (token) code = code ? `${code}-${token}` : token;
	if (code && parts.length) code = `${code}-${parts.join('_')}`;
	return code;
});

// While in auto mode, keep the field in sync with the composed code.
watch(
	autoCode,
	(code) => {
		if (isExistingItem()) return;   // never auto-emit for saved records
		if (!manual.value && code && code !== props.value) emit('input', code);
	},
	{ immediate: true },
);

function onType(val: string | null) {
	emit('input', val);
	// Empty input drops back into auto mode; anything else is a manual override.
	manual.value = !!val && val !== autoCode.value;
}

function regenerate() {
	manual.value = false;
	if (autoCode.value) emit('input', autoCode.value);
}
</script>

<style scoped>
.d1-operation-code { width: 100%; }
.hint {
	display: block;
	margin-top: 4px;
	font-size: 12px;
	color: var(--theme--foreground-subdued, #999);
	font-style: italic;
}
.v-icon.active { color: var(--theme--primary, #1565c0); }
</style>
