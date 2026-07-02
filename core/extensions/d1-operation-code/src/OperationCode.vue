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

const props = defineProps<{ value: string | null }>();
const emit = defineEmits<{ (e: 'input', value: string | null): void }>();

const values = inject<Ref<Record<string, any>>>('values', ref({}));
const api = useApi();

// Existing records arrive with a value already set — never auto-clobber those.
const manual = ref<boolean>(!!props.value);

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

	let token = '';
	let parts: string[] = [];

	if (cat === 'machining') {
		const pass = v.operation_sequence;
		const passStr = pass === '' || pass === null || pass === undefined ? '' : String(pass);
		token = `${v.machining_operation_subtype ?? ''}${passStr}`;
		parts = [
			num(v.machining_cutting_speed_m_per_min) && `${num(v.machining_cutting_speed_m_per_min)}MPM`,
			num(v.machining_feed_mm_per_rev) && `${num(v.machining_feed_mm_per_rev)}feed`,
			num(v.machining_axial_depth_of_cut_mm) && `${num(v.machining_axial_depth_of_cut_mm)}DoC`,
		].filter(Boolean) as string[];
	} else if (cat === 'sintering') {
		token = 'MF';
		parts = [
			num(v.sintering_max_temp_celsius) && `${num(v.sintering_max_temp_celsius)}C`,
			num(v.sintering_max_force_kn) && `${num(v.sintering_max_force_kn)}kN`,
			num(v.sintering_mould_diameter_mm) && `${num(v.sintering_mould_diameter_mm)}dia`,
		].filter(Boolean) as string[];
	} else if (cat === 'heat_treatment') {
		token = `HT${HT_TYPE[v.ht_treatment_type] ?? ''}`;
		parts = [
			num(v.ht_peak_temp_celsius) && `${num(v.ht_peak_temp_celsius)}C`,
			num(v.ht_hold_time_min) && `${num(v.ht_hold_time_min)}min`,
			HT_COOL[v.ht_cooling_method],
		].filter(Boolean) as string[];
	} else if (cat === 'deformation') {
		token = DEFORM_TOKEN[v.deform_deformation_type] ?? 'D';
		parts = [
			num(v.deform_deformation_temp_celsius) && `${num(v.deform_deformation_temp_celsius)}C`,
			num(v.deform_total_reduction_pct) && `${num(v.deform_total_reduction_pct)}pct`,
			num(v.deform_pass_count) && `${num(v.deform_pass_count)}p`,
		].filter(Boolean) as string[];
	} else if (cat === 'additive') {
		token = (v.am_process_variant ?? 'AM') as string;
		parts = [
			num(v.am_laser_power_w) && `${num(v.am_laser_power_w)}W`,
			num(v.am_scan_speed_mm_per_s) && `${num(v.am_scan_speed_mm_per_s)}mmps`,
			num(v.am_layer_thickness_mm) && `${num(v.am_layer_thickness_mm)}mm`,
		].filter(Boolean) as string[];
	} else {
		return sample; // unknown category — just the sample code
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
