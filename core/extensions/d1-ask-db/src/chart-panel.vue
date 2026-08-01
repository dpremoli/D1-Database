<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import Plotly from 'plotly.js-dist-min';

// A validated chart spec from the backend (app/lib/charts.py). Only these shapes
// reach us — x/y are guaranteed to be real column names, type is on the allow-list.
interface ChartSpec {
	type: 'bar' | 'line' | 'scatter' | 'histogram' | 'pie';
	x: string;
	y: string[];
	title?: string;
}

const props = defineProps<{
	spec: ChartSpec;
	rows: Record<string, unknown>[];
}>();

const el = ref<HTMLDivElement | null>(null);

/** Map the (already-safe) spec + rows onto Plotly traces. */
function buildTraces(spec: ChartSpec, rows: Record<string, unknown>[]): unknown[] {
	const xValues = rows.map((r) => r[spec.x]);

	if (spec.type === 'histogram') {
		return [{ x: xValues, type: 'histogram' }];
	}
	if (spec.type === 'pie') {
		const valueCol = spec.y[0];
		return [{ labels: xValues, values: rows.map((r) => r[valueCol]), type: 'pie' }];
	}

	// bar / line / scatter: one trace per y series.
	const base =
		spec.type === 'bar'
			? { type: 'bar' }
			: { type: 'scatter', mode: spec.type === 'line' ? 'lines+markers' : 'markers' };

	return spec.y.map((col) => ({
		...base,
		name: col,
		x: xValues,
		y: rows.map((r) => r[col]),
	}));
}

function render() {
	if (!el.value) return;
	const layout = {
		title: props.spec.title ?? '',
		margin: { t: props.spec.title ? 40 : 16, r: 16, b: 48, l: 56 },
		height: 360,
		font: { family: 'inherit' },
		paper_bgcolor: 'transparent',
		plot_bgcolor: 'transparent',
	};
	Plotly.newPlot(el.value, buildTraces(props.spec, props.rows), layout, {
		responsive: true,
		displayModeBar: false,
	});
}

onMounted(render);
watch(() => [props.spec, props.rows], render, { deep: true });
onBeforeUnmount(() => {
	if (el.value) Plotly.purge(el.value);
});
</script>

<template>
	<div ref="el" data-test="ask-chart" class="ask-chart" />
</template>

<style scoped>
.ask-chart {
	width: 100%;
	min-height: 360px;
}
</style>
