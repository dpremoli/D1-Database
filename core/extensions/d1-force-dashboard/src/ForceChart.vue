<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue';

// Dependency-free chart. kind='env' → min/max envelope (force or RPM; always
// includes 0 on the y-axis); kind='line' → FFT amplitude (optional log y).
// Width AND height track the container (ResizeObserver) so the viewBox is 1:1
// with pixels — no stretching, and the plot grows to fill available vertical
// space. Hover is driven by a shared index so all three/four charts scrub
// together. For 'env' charts, cropStart/cropEnd (same units as the x-axis —
// seconds) render the discarded lead-in/out at low saturation and the actual
// analysed window (what feeds the FRM map) at full saturation.
const props = defineProps<{
	title: string;
	kind: 'env' | 'line';
	data: any;
	color?: string;
	xUnit?: string;
	yUnit?: string;
	logY?: boolean;
	hoverIndex?: number | null;
	cropStart?: number | null;
	cropEnd?: number | null;
	cropEditable?: boolean;           // Live mode: draggable crop handles that emit updates
	peak?: number | string | null;   // Postgres NUMERIC often arrives as a string over the API
	viewStart?: number | null;       // shared x-zoom window (x-units); null = full range
	viewEnd?: number | null;
	zoomTool?: boolean;              // when true, drag draws a rectangular zoom box
}>();
const emit = defineEmits<{
	(e: 'hover', i: number | null): void;
	(e: 'update:cropStart', v: number): void;
	(e: 'update:cropEnd', v: number): void;
	(e: 'zoom', v: { start: number; end: number } | null): void;   // null = reset to full
}>();

const ML = 46, MR = 12, MT = 8, MB = 24;
const stroke = computed(() => props.color || '#0d9488');
const peakNum = computed(() => {
	if (props.peak == null) return null;
	const n = Number(props.peak);
	return Number.isFinite(n) ? n : null;
});

const svgEl = ref<SVGSVGElement | null>(null);
const w = ref(360);
const h = ref(150);
let ro: ResizeObserver | undefined;
onMounted(() => {
	ro = new ResizeObserver((entries) => {
		const r = entries[0].contentRect;
		if (r.width > 0) w.value = Math.round(r.width);
		if (r.height > 0) h.value = Math.round(r.height);
	});
	if (svgEl.value) ro.observe(svgEl.value);
});
onBeforeUnmount(() => ro?.disconnect());

function niceNum(v: number): string {
	const a = Math.abs(v);
	if (a === 0) return '0';
	if (a >= 1000) return `${(v / 1000).toFixed(1)}k`;
	if (a >= 100) return v.toFixed(0);
	if (a >= 10) return v.toFixed(1);
	if (a >= 1) return v.toFixed(2);
	if (a >= 0.01) return v.toFixed(3);
	return v.toExponential(0);
}

// A "nice" step (1/2/5 * 10^n) so evenly-spaced x-ticks land on round numbers
// rather than arbitrary fractions.
function niceStep(rough: number): number {
	if (!(rough > 0)) return 1;
	const pow = 10 ** Math.floor(Math.log10(rough));
	const f = rough / pow;
	const nice = f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10;
	return nice * pow;
}

const geom = computed(() => {
	const d = props.data;
	if (!d) return null;
	const xs: number[] = props.kind === 'env' ? d.t : d.f;
	if (!xs || xs.length < 2) return null;
	const W = w.value, Hh = h.value;
	const plotH = Hh - MT - MB;
	const plotW = W - ML - MR;

	// Visible x-window (shared zoom). Snap the index range to the requested view
	// so the y-axis auto-rescales to just the zoomed data, and the x-axis spans
	// exactly the requested bounds (smooth, not sample-snapped).
	const dataX0 = xs[0], dataX1 = xs[xs.length - 1];
	let x0 = props.viewStart != null ? Math.max(dataX0, props.viewStart) : dataX0;
	let x1 = props.viewEnd != null ? Math.min(dataX1, props.viewEnd) : dataX1;
	if (!(x1 > x0)) { x0 = dataX0; x1 = dataX1; }
	let iA = 0, iB = xs.length - 1;
	while (iA < iB && xs[iA + 1] < x0) iA++;
	while (iB > iA && xs[iB - 1] > x1) iB--;

	let lo = Infinity, hi = -Infinity;
	if (props.kind === 'env') {
		for (let i = iA; i <= iB; i++) { if (d.min[i] < lo) lo = d.min[i]; if (d.max[i] > hi) hi = d.max[i]; }
		lo = Math.min(lo, 0); hi = Math.max(hi, 0);       // always include 0
	} else {
		lo = 0;
		for (let i = iA; i <= iB; i++) if (d.amp[i] > hi) hi = d.amp[i];
	}
	if (!isFinite(lo) || !isFinite(hi)) { lo = 0; hi = 1; }
	if (hi === lo) hi = lo + 1;

	const sx = (x: number) => ML + ((x - x0) / (x1 - x0)) * plotW;

	let sy: (y: number) => number;
	let yticks: { y: number; label: string }[];
	const useLog = props.logY === true && props.kind === 'line' && hi > 0;
	if (useLog) {
		let minPos = Infinity;
		for (let i = iA; i <= iB; i++) if (d.amp[i] > 0 && d.amp[i] < minPos) minPos = d.amp[i];
		if (!isFinite(minPos)) minPos = hi / 1e5;
		const loRaw = Math.max(minPos, hi / 1e5);          // clamp to 5 decades below peak
		const L0 = Math.log10(loRaw), L1 = Math.log10(hi);
		const den = (L1 - L0) || 1;
		sy = (y) => MT + (1 - (Math.log10(Math.max(y, loRaw)) - L0) / den) * plotH;
		yticks = [];
		for (let k = Math.ceil(L0); k <= Math.floor(L1); k++) yticks.push({ y: sy(10 ** k), label: niceNum(10 ** k) });
		if (yticks.length < 2) yticks = [loRaw, hi].map((v) => ({ y: sy(v), label: niceNum(v) }));
	} else {
		sy = (y) => MT + (1 - (y - lo) / (hi - lo)) * plotH;
		const vals = (props.kind === 'env' && lo < 0 && hi > 0) ? [hi, 0, lo] : [hi, (lo + hi) / 2, lo];
		yticks = vals.map((v) => ({ y: sy(v), label: niceNum(v) }));
	}

	function areaPath(a: number, b: number): string {
		const i0 = Math.max(0, Math.min(a, xs.length - 1));
		const i1 = Math.max(0, Math.min(b, xs.length - 1));
		let up = 'M';
		for (let i = i0; i <= i1; i++) up += `${sx(xs[i]).toFixed(1)},${sy(d.max[i]).toFixed(1)} `;
		let dn = '';
		for (let i = i1; i >= i0; i--) dn += `${sx(xs[i]).toFixed(1)},${sy(d.min[i]).toFixed(1)} `;
		return `${up}L ${dn}Z`;
	}

	let area = '', line = '', cropArea = '';
	if (props.kind === 'env') {
		area = areaPath(iA, iB);
		if (props.cropStart != null && props.cropEnd != null) {
			// i0 = -1 when the crop starts after all data; revIdx = -1 when it ends
			// before all data — in both cases there's no in-range window to shade
			// (guard, else areaPath would index past the array and emit NaN paths).
			// Clamp to the visible [iA,iB] window so a zoom doesn't paint off-plot.
			const i0 = Math.max(iA, xs.findIndex((v) => v >= props.cropStart!));
			const revIdx = [...xs].reverse().findIndex((v) => v <= props.cropEnd!);
			const i1 = revIdx < 0 ? -1 : Math.min(iB, xs.length - 1 - revIdx);
			if (i0 >= iA && i1 >= i0) cropArea = areaPath(i0, i1);
		}
	} else {
		line = 'M';
		for (let i = iA; i <= iB; i++) line += `${sx(xs[i]).toFixed(1)},${sy(d.amp[i]).toFixed(1)} `;
	}

	// Evenly-spaced "regular" ticks at a nice round step, aimed at ~80px apart.
	const targetCount = Math.max(4, Math.min(12, Math.round(plotW / 80)));
	const step = niceStep((x1 - x0) / targetCount) || (x1 - x0) || 1;
	const xticks: { x: number; label: string }[] = [];
	const first = Math.ceil(x0 / step) * step;
	for (let v = first; v <= x1 + step * 1e-6; v += step) {
		if (v < x0 - step * 1e-6) continue;
		xticks.push({ x: sx(v), label: niceNum(v) });
	}
	if (xticks.length < 2) { xticks.length = 0; xticks.push({ x: sx(x0), label: niceNum(x0) }, { x: sx(x1), label: niceNum(x1) }); }

	const zeroY = (lo < 0 && hi > 0) ? sy(0) : null;
	const cropStartX = props.cropStart != null ? sx(props.cropStart) : null;
	const cropEndX = props.cropEnd != null ? sx(props.cropEnd) : null;
	return { W, Hh, xs, x0, x1, iA, iB, lo, hi, sx, sy, area, line, cropArea, xticks, yticks, zeroY, cropStartX, cropEndX };
});

const hoverPt = computed(() => {
	const g = geom.value;
	const i = props.hoverIndex;
	if (!g || i == null || i < g.iA || i > g.iB) return null;
	const d = props.data;
	if (props.kind === 'env') {
		const mid = (d.min[i] + d.max[i]) / 2;
		return { px: g.sx(g.xs[i]), py: g.sy(mid),
			label: `${mid.toFixed(2)} ${props.yUnit || ''}`.trim(), sub: `${niceNum(g.xs[i])} ${props.xUnit || ''}`.trim() };
	}
	return { px: g.sx(g.xs[i]), py: g.sy(d.amp[i]),
		label: `${d.amp[i].toPrecision(3)}`, sub: `${niceNum(g.xs[i])} ${props.xUnit || 'Hz'}`.trim() };
});

function onMove(ev: MouseEvent) {
	const g = geom.value;
	if (!g) return;
	const r = (ev.currentTarget as SVGElement).getBoundingClientRect();
	const px = (ev.clientX - r.left) * (g.W / r.width);
	const frac = (px - ML) / (g.W - ML - MR);
	const i = Math.round(Math.min(1, Math.max(0, frac)) * (g.xs.length - 1));
	emit('hover', i);
}
function onLeave() { emit('hover', null); }

// ---- draggable crop handles (Live mode) ----
let dragging: 'start' | 'end' | null = null;
function xToSec(ev: PointerEvent): number {
	const g = geom.value, svg = svgEl.value;
	if (!g || !svg) return 0;
	const r = svg.getBoundingClientRect();
	const px = (ev.clientX - r.left) * (g.W / r.width);
	const frac = (px - ML) / (g.W - ML - MR);
	return g.x0 + Math.min(1, Math.max(0, frac)) * (g.x1 - g.x0);
}
function onCropDown(ev: PointerEvent) {
	if (!props.cropEditable || !geom.value) return;
	const sec = xToSec(ev);
	const ds = props.cropStart != null ? Math.abs(sec - props.cropStart) : Infinity;
	const de = props.cropEnd != null ? Math.abs(sec - props.cropEnd) : Infinity;
	dragging = ds <= de ? 'start' : 'end';
	(ev.currentTarget as Element).setPointerCapture(ev.pointerId);
	ev.stopPropagation();
	onCropMove(ev);
}
function onCropMove(ev: PointerEvent) {
	if (!dragging) return;
	const sec = xToSec(ev);
	if (dragging === 'start') emit('update:cropStart', props.cropEnd != null ? Math.min(sec, props.cropEnd) : sec);
	else emit('update:cropEnd', props.cropStart != null ? Math.max(sec, props.cropStart) : sec);
	ev.stopPropagation();
}
function onCropUp(ev: PointerEvent) {
	dragging = null;
	try { (ev.currentTarget as Element).releasePointerCapture(ev.pointerId); } catch { /* ignore */ }
}

// ---- x-zoom: wheel + rectangular selection (emits a shared window to the parent) ----
function pxOf(ev: PointerEvent | WheelEvent): number {
	const g = geom.value, svg = svgEl.value;
	if (!g || !svg) return 0;
	const r = svg.getBoundingClientRect();
	return ((ev as any).clientX - r.left) * (g.W / r.width);
}
function fracToX(frac: number): number {
	const g = geom.value!;
	return g.x0 + Math.min(1, Math.max(0, frac)) * (g.x1 - g.x0);
}
const zoomRect = ref<{ x: number; w: number } | null>(null);
let zoomDrag = false, zStartPx = 0;
function onZoomDown(ev: PointerEvent) {
	if (!props.zoomTool || !geom.value) return;
	zoomDrag = true; zStartPx = pxOf(ev); zoomRect.value = { x: zStartPx, w: 0 };
	(ev.currentTarget as Element).setPointerCapture(ev.pointerId); ev.stopPropagation();
}
function onZoomMove(ev: PointerEvent) {
	if (!zoomDrag) return;
	const px = pxOf(ev);
	zoomRect.value = { x: Math.min(px, zStartPx), w: Math.abs(px - zStartPx) };
	ev.stopPropagation();
}
function onZoomUp(ev: PointerEvent) {
	if (!zoomDrag) return;
	zoomDrag = false;
	const g = geom.value, rsel = zoomRect.value;
	zoomRect.value = null;
	try { (ev.currentTarget as Element).releasePointerCapture(ev.pointerId); } catch { /* ignore */ }
	if (!g || !rsel || rsel.w < 6) return;
	const clamp = (px: number) => (px - ML) / (g.W - ML - MR);
	const s = fracToX(clamp(rsel.x)), e = fracToX(clamp(rsel.x + rsel.w));
	if (e > s) emit('zoom', { start: s, end: e });
}
function onWheel(ev: WheelEvent) {
	const g = geom.value;
	if (!g) return;
	ev.preventDefault();
	const frac = (pxOf(ev) - ML) / (g.W - ML - MR);
	const cursorX = fracToX(frac);
	const dataSpan = g.xs[g.xs.length - 1] - g.xs[0];
	const f = ev.deltaY < 0 ? 1 / 1.3 : 1.3;
	let span = Math.min(dataSpan, Math.max(dataSpan / 1000, (g.x1 - g.x0) * f));
	let s = cursorX - Math.min(1, Math.max(0, frac)) * span, e = s + span;
	const dx0 = g.xs[0], dx1 = g.xs[g.xs.length - 1];
	if (s < dx0) { e += dx0 - s; s = dx0; }
	if (e > dx1) { s -= e - dx1; e = dx1; }
	s = Math.max(dx0, s);
	emit('zoom', (e - s >= dataSpan * 0.999) ? null : { start: s, end: e });
}
</script>

<template>
	<div class="chart">
		<div class="chart-head">
			<span class="chart-title">{{ title }}</span>
			<span v-if="peakNum != null" class="chart-peak">peak {{ peakNum.toFixed(2) }} {{ yUnit }}</span>
			<span v-else-if="geom" class="chart-unit">{{ logY ? 'log ' : '' }}{{ yUnit || (kind === 'line' ? 'amp' : '') }}</span>
		</div>
		<svg
			ref="svgEl" v-if="geom" :viewBox="`0 0 ${geom.W} ${geom.Hh}`" class="chart-svg" :class="{ zoomtool: zoomTool }"
			preserveAspectRatio="none" @mousemove="onMove" @mouseleave="onLeave" @wheel="onWheel"
			@pointerdown="onZoomDown" @pointermove="onZoomMove" @pointerup="onZoomUp" @pointercancel="onZoomUp"
		>
			<line v-for="(t, i) in geom.yticks" :key="'gy' + i" :x1="ML" :x2="geom.W - MR" :y1="t.y" :y2="t.y" stroke="#e2e8f0" stroke-width="0.5" />
			<line v-for="(t, i) in geom.xticks" :key="'gx' + i" :x1="t.x" :x2="t.x" :y1="MT" :y2="geom.Hh - MB" stroke="#eef1f5" stroke-width="0.5" />
			<line v-if="geom.zeroY != null" :x1="ML" :x2="geom.W - MR" :y1="geom.zeroY" :y2="geom.zeroY" stroke="#cbd5e1" stroke-width="0.9" />
			<!-- full-range area at low saturation; the analysed [cropStart,cropEnd] window overpaints at full saturation -->
			<path v-if="kind === 'env'" :d="geom.area" :fill="stroke" :fill-opacity="geom.cropArea ? 0.09 : 0.2" :stroke="stroke" stroke-opacity="0.35" stroke-width="0.6" />
			<path v-if="kind === 'env' && geom.cropArea" :d="geom.cropArea" :fill="stroke" fill-opacity="0.28" :stroke="stroke" stroke-width="0.8" />
			<path v-if="kind === 'line'" :d="geom.line" fill="none" :stroke="stroke" stroke-width="1.1" />
			<line :x1="ML" :x2="ML" :y1="MT" :y2="geom.Hh - MB" stroke="#94a3b8" stroke-width="0.8" />
			<line :x1="ML" :x2="geom.W - MR" :y1="geom.Hh - MB" :y2="geom.Hh - MB" stroke="#94a3b8" stroke-width="0.8" />
			<g v-for="(t, i) in geom.yticks" :key="'y' + i">
				<line :x1="ML - 3" :x2="ML" :y1="t.y" :y2="t.y" stroke="#94a3b8" stroke-width="0.8" />
				<text :x="ML - 5" :y="t.y + 2.5" text-anchor="end" class="tick">{{ t.label }}</text>
			</g>
			<g v-for="(t, i) in geom.xticks" :key="'x' + i">
				<line :x1="t.x" :x2="t.x" :y1="geom.Hh - MB" :y2="geom.Hh - MB + 3" stroke="#94a3b8" stroke-width="0.8" />
				<text :x="t.x" :y="geom.Hh - MB + 12" text-anchor="middle" class="tick">{{ t.label }}</text>
			</g>
			<text :x="(ML + geom.W - MR) / 2" :y="geom.Hh - 3" text-anchor="middle" class="axis-label">{{ xUnit }}</text>
			<g v-if="hoverPt">
				<line :x1="hoverPt.px" :x2="hoverPt.px" :y1="MT" :y2="geom.Hh - MB" stroke="#64748b" stroke-width="0.6" stroke-dasharray="3 3" />
				<circle :cx="hoverPt.px" :cy="hoverPt.py" r="2.8" :fill="stroke" />
			</g>
			<!-- Live-mode draggable crop handles (start = teal, end = red); wide invisible
			     hit rects keep them easy to grab. Pointer events are captured on drag. -->
			<g v-if="cropEditable">
				<template v-for="(hx, k) in [{ x: geom.cropStartX, c: '#0f766e' }, { x: geom.cropEndX, c: '#b91c1c' }]" :key="'ch' + k">
					<template v-if="hx.x != null">
						<line :x1="hx.x" :x2="hx.x" :y1="MT" :y2="geom.Hh - MB" :stroke="hx.c" stroke-width="1.4" />
						<rect :x="hx.x - 3" :y="MT" width="6" :height="geom.Hh - MB - MT" :fill="hx.c" fill-opacity="0.001"
							class="crop-hit" @pointerdown="onCropDown" @pointermove="onCropMove" @pointerup="onCropUp" @pointercancel="onCropUp" />
						<rect :x="hx.x - 3.5" :y="MT" width="7" height="5" :fill="hx.c" />
					</template>
				</template>
			</g>
			<!-- rubber-band x-zoom rectangle -->
			<rect v-if="zoomRect" :x="zoomRect.x" :y="MT" :width="zoomRect.w" :height="geom.Hh - MB - MT"
				fill="#38bdf8" fill-opacity="0.16" stroke="#0ea5e9" stroke-width="0.8" />
		</svg>
		<div v-else class="chart-empty">no data</div>
		<div v-if="hoverPt" class="chart-tip"><strong>{{ hoverPt.label }}</strong><span>{{ hoverPt.sub }}</span></div>
	</div>
</template>

<style scoped>
.chart {
	position: relative;
	background: var(--theme--background, #fff);
	border: 1px solid var(--theme--border-color-subdued, #e7ebf0);
	border-radius: 14px; padding: 10px 12px 6px; min-width: 0; min-height: 150px;
	display: flex; flex-direction: column;
}
.chart-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 2px; gap: 8px; flex: 0 0 auto; }
.chart-title { font-size: 12.5px; font-weight: 650; color: var(--theme--foreground, #1e293b); }
.chart-unit { font-size: 10.5px; color: var(--theme--foreground-subdued, #98a2b3); font-weight: 600; }
.chart-peak { font-size: 10.5px; color: var(--theme--foreground, #1e293b); font-weight: 700; font-variant-numeric: tabular-nums; }
.chart-svg { display: block; width: 100%; flex: 1 1 auto; min-height: 0; cursor: crosshair; touch-action: none; }
.chart-svg.zoomtool { cursor: crosshair; }
.chart-svg .tick { fill: var(--theme--foreground-subdued, #94a3b8); font-size: 8px; font-variant-numeric: tabular-nums; }
.chart-svg .axis-label { fill: var(--theme--foreground-subdued, #94a3b8); font-size: 8px; }
.chart-svg .crop-hit { cursor: ew-resize; }
.chart-empty { flex: 1; display: grid; place-items: center; color: var(--theme--foreground-subdued, #98a2b3); font-size: 12px; }
.chart-tip {
	position: absolute; top: 8px; right: 12px; display: flex; flex-direction: column; align-items: flex-end;
	background: color-mix(in srgb, var(--theme--background, #fff) 85%, transparent); border-radius: 8px; padding: 2px 7px; pointer-events: none;
}
.chart-tip strong { font-size: 12px; font-variant-numeric: tabular-nums; }
.chart-tip span { font-size: 10px; color: var(--theme--foreground-subdued, #98a2b3); }
</style>
