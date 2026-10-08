<script setup lang="ts">
// ForceChart's hover crosshair + dot (part="svg", inside the <svg>) and its readout (part="tip",
// outside it), split out of the chart so a mouse move redraws only these (#100). The hover index is
// shared by every open chart and changes on each move; ForceChart used to read it in its own
// template, so every move re-rendered every chart's grid, ticks and paths. The index now arrives as
// a stable HoverSource and is read only here, so ForceChart's render never subscribes to it.
import { computed } from 'vue';
import { hoverPoint, type HoverGeom, type HoverSource } from './chartHover';

const props = defineProps<{
	part: 'svg' | 'tip';
	hover?: HoverSource;
	geom: HoverGeom;
	kind: 'env' | 'line';
	data: any;
	yLabelUnit: string;
	xUnit?: string;
	stroke: string;
	top: number;       // plot area top / bottom edges (the crosshair's extent)
	bottom: number;
}>();

const pt = computed(() => hoverPoint(props.geom, props.hover?.index.value, props.kind, props.data, props.yLabelUnit, props.xUnit));
</script>

<template>
	<g v-if="part === 'svg' && pt">
		<line :x1="pt.px" :x2="pt.px" :y1="top" :y2="bottom" stroke="#64748b" stroke-width="0.6" stroke-dasharray="3 3" />
		<circle :cx="pt.px" :cy="pt.py" r="2.8" :fill="stroke" />
	</g>
	<div v-else-if="part === 'tip' && pt" class="chart-tip"><strong>{{ pt.label }}</strong><span>{{ pt.sub }}</span></div>
</template>

<style scoped>
.chart-tip {
	/* below the header row so it never covers the "peak … N" readout in the top-right */
	position: absolute; top: 30px; right: 12px; display: flex; flex-direction: column; align-items: flex-end;
	background: color-mix(in srgb, var(--theme--background, #fff) 85%, transparent); border-radius: 8px; padding: 2px 7px; pointer-events: none;
}
.chart-tip strong { font-size: var(--fs-sm, 12px); font-variant-numeric: tabular-nums; }
.chart-tip span { font-size: var(--fs-xs, 11px); color: var(--theme--foreground-subdued, #98a2b3); }
</style>
