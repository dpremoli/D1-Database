<script setup lang="ts">
// Static full-resolution force trace for a completed cut — draws every sample of the finished
// live-cache (Fx/Fy/Fz vs t) once, unlike LiveForcePlot which streams a rolling window. Used
// wherever a finished recording's full time series needs to be shown (ForcePanel post-stop,
// SaveCutDialog).
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import type { Cache } from '@d1/force-plotting';
import { channelColor } from './types';
import { theme } from '../theme';
import { decimateMinMax, seriesRange, shouldDecimate } from './traceDecimate';

const props = defineProps<{
	cache: Cache;
	channels?: string[];
	// Override the cache's own auto-detected csSec/ceSec for the shaded cut window — the
	// end-of-cut save dialog seeds these from csSec/ceSec but lets the operator drag them before
	// saving (#7). Falls back to the cache's own values when not given, same shading as before.
	cropStartSec?: number | null;
	cropEndSec?: number | null;
	cropEditable?: boolean;
}>();
const emit = defineEmits<{
	(e: 'update:cropStartSec', v: number): void;
	(e: 'update:cropEndSec', v: number): void;
}>();
const canvasEl = ref<HTMLCanvasElement | null>(null);
let ctx: CanvasRenderingContext2D | null = null;
let ro: ResizeObserver | null = null;

// MB fits the tick labels (4-14px below the plot) AND the axis title under them; at 22 the
// title was drawn top-aligned 4px above the canvas edge and always clipped to half its height.
const ML = 48, MR = 10, MT = 10, MB = 32;
// Updated every draw() so pointer handlers can convert canvas-local px <-> data seconds without
// redoing the layout math.
let lastT0 = 0, lastT1 = 0, lastW = 0;
function xToSec(px: number): number {
	if (lastW <= 0) return lastT0;
	const t = lastT0 + ((px - ML) / lastW) * (lastT1 - lastT0);
	return Math.min(lastT1, Math.max(lastT0, t));
}
let lastHandles: { startX: number; endX: number; top: number; bottom: number } | null = null;
let dragging: 'start' | 'end' | null = null;

function localPx(ev: PointerEvent): { x: number; y: number } {
	const r = canvasEl.value!.getBoundingClientRect();
	return { x: ev.clientX - r.left, y: ev.clientY - r.top };
}
function onPointerDown(ev: PointerEvent) {
	if (!props.cropEditable || !lastHandles) return;
	const { x, y } = localPx(ev);
	if (y < lastHandles.top - 6 || y > lastHandles.bottom + 6) return;
	const ds = Math.abs(x - lastHandles.startX), de = Math.abs(x - lastHandles.endX);
	const nearest = ds <= de ? 'start' : 'end';
	if (Math.min(ds, de) > 10) return;   // clicked well away from either handle — not a drag
	dragging = nearest;
	(ev.target as Element).setPointerCapture(ev.pointerId);
}
function onPointerMove(ev: PointerEvent) {
	if (!dragging) return;
	const sec = xToSec(localPx(ev).x);
	if (dragging === 'start') emit('update:cropStartSec', Math.min(sec, props.cropEndSec ?? sec));
	else emit('update:cropEndSec', Math.max(sec, props.cropStartSec ?? sec));
}
function onPointerUp() { dragging = null; }

function resize() {
	const c = canvasEl.value;
	if (!c) return;
	const r = c.getBoundingClientRect();
	const dpr = Math.min(window.devicePixelRatio || 1, 2);
	c.width = Math.max(1, Math.floor(r.width * dpr));
	c.height = Math.max(1, Math.floor(r.height * dpr));
	ctx = c.getContext('2d');
	if (ctx) ctx.scale(dpr, dpr);
	layer = null;   // sized for the old canvas
	scheduleDraw();
}

function palette() {
	const s = getComputedStyle(document.documentElement);
	return {
		bg: s.getPropertyValue('--plot-bg').trim() || '#0b1020',
		grid: s.getPropertyValue('--border').trim() || 'rgba(255,255,255,0.06)',
		axisLine: s.getPropertyValue('--border-2').trim() || 'rgba(255,255,255,0.2)',
		text: s.getPropertyValue('--text-dim').trim() || 'rgba(226,232,240,0.55)',
		textFaint: s.getPropertyValue('--text-faint').trim() || 'rgba(226,232,240,0.45)',
	};
}

function niceStep(range: number, ticks: number): number {
	const raw = range / ticks;
	const mag = Math.pow(10, Math.floor(Math.log10(raw)));
	const r = raw / mag;
	return (r <= 1.5 ? 1 : r <= 3 ? 2 : r <= 7 ? 5 : 10) * mag;
}

function seriesOf(key: string): Float32Array | undefined {
	const c = props.cache;
	return key === 'Fx' ? c.Fx : key === 'Fy' ? c.Fy : key === 'Fz' ? c.Fz : undefined;
}

// Everything that does not move while a crop handle is dragged -- background, grid, axes, labels
// and the (decimated) traces -- is painted once onto an offscreen canvas and only blitted per
// frame. It is rebuilt when the cache, the channel set, the canvas size or the theme changes.
// (#77: it used to restyle, rescan 250k+ samples and stroke every polyline on each pointermove.)
interface Layer {
	key: string;
	cache: Cache;
	canvas: HTMLCanvasElement;
	t0: number; t1: number; W: number; H: number; lo: number; yr: number;
}
let layer: Layer | null = null;
// Min/max over the whole cache depends only on the cache and channel set, not on the size.
let rangeCache: { cache: Cache; sel: string; range: [number, number] | null } | null = null;

function dataRange(sel: string[], series: readonly (readonly [string, Float32Array])[]): [number, number] | null {
	const sk = sel.join(',');
	if (rangeCache && rangeCache.cache === props.cache && rangeCache.sel === sk) return rangeCache.range;
	const range = seriesRange(series.map(([, a]) => a));
	rangeCache = { cache: props.cache, sel: sk, range };
	return range;
}

function buildLayer(CW: number, CH: number, dpr: number): Layer | null {
	const cache = props.cache;
	const n = cache.t.length;
	const sel = (props.channels ?? ['Fx', 'Fy', 'Fz']).filter((k) => k === 'Fx' || k === 'Fy' || k === 'Fz');
	const pal = palette();
	const W = CW - ML - MR, H = CH - MT - MB;
	const off = document.createElement('canvas');
	off.width = Math.max(1, Math.floor(CW * dpr)); off.height = Math.max(1, Math.floor(CH * dpr));
	const g = off.getContext('2d');
	if (!g) return null;
	g.scale(dpr, dpr);
	g.fillStyle = pal.bg;
	g.fillRect(0, 0, CW, CH);

	const t0 = n ? cache.t[0] : 0, t1 = n ? cache.t[n - 1] : 0;
	const base = { key: '', cache, canvas: off, t0, t1, W, H, lo: 0, yr: 1 };
	if (n < 2) {
		g.fillStyle = pal.text; g.font = '12px system-ui';
		g.fillText('no data', ML + 8, MT + H / 2);
		return base;
	}

	const span = Math.max(1e-3, t1 - t0);
	const series = sel.map((k) => [k, seriesOf(k)!] as const).filter(([, a]) => a && a.length > 0);
	let [lo, hi] = dataRange(sel, series) ?? [-1, 1];
	const pad = 0.1 * (hi - lo || 1);
	lo -= pad; hi += pad;
	const yr = hi - lo || 1;

	const xOf = (t: number) => ML + ((t - t0) / span) * W;
	const yOf = (v: number) => MT + H - ((v - lo) / yr) * H;

	g.font = '10px system-ui'; g.textAlign = 'right'; g.textBaseline = 'middle';
	const yStep = niceStep(yr, Math.max(2, Math.floor(H / 50)));
	const yStart = Math.ceil(lo / yStep) * yStep;
	g.strokeStyle = pal.grid; g.lineWidth = 1;
	for (let v = yStart; v <= hi; v += yStep) {
		const y = yOf(v);
		if (y < MT || y > MT + H) continue;
		g.beginPath(); g.moveTo(ML, y); g.lineTo(ML + W, y); g.stroke();
		g.fillStyle = pal.text;
		g.fillText(Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + 'k' : Number.isInteger(v) ? String(v) : v.toFixed(1), ML - 5, y);
	}

	g.textAlign = 'center'; g.textBaseline = 'top';
	const xStep = niceStep(span, Math.max(2, Math.floor(W / 80)));
	const xStart = Math.ceil(t0 / xStep) * xStep;
	for (let t = xStart; t <= t1; t += xStep) {
		const x = xOf(t);
		if (x < ML || x > ML + W) continue;
		g.beginPath(); g.moveTo(x, MT); g.lineTo(x, MT + H); g.stroke();
		g.fillStyle = pal.text;
		g.fillText(t.toFixed(t >= 100 ? 0 : 1), x, MT + H + 4);
	}

	g.fillStyle = pal.textFaint; g.font = '10px system-ui';
	g.textAlign = 'center'; g.textBaseline = 'bottom';
	g.fillText('Time (s)', ML + W / 2, CH - 2);
	g.save(); g.translate(10, MT + H / 2); g.rotate(-Math.PI / 2);
	g.textBaseline = 'middle'; g.fillText('Force (N)', 0, 0); g.restore();

	if (lo < 0 && hi > 0) { g.strokeStyle = pal.axisLine; g.lineWidth = 1; g.beginPath(); g.moveTo(ML, yOf(0)); g.lineTo(ML + W, yOf(0)); g.stroke(); }

	// The cut-window shade is painted per frame (see draw()), over the traces: at 6% alpha it is
	// indistinguishable from painting it underneath.
	const cols = Math.max(1, Math.round(W * dpr));
	for (const [key, arr] of series) {
		const col = channelColor(key, theme.value) ?? '#94a3b8';
		g.globalAlpha = 0.9; g.strokeStyle = col; g.lineWidth = 1.2;
		g.beginPath();
		if (shouldDecimate(n, cols)) {
			const d = decimateMinMax(cache.t, arr, t0, t1, cols);
			let started = false;
			const pt = (c: number, v: number) => {
				if (Number.isNaN(v)) return;
				const x = ML + ((c + 0.5) / d.cols) * W, y = yOf(v);
				if (started) g.lineTo(x, y); else { g.moveTo(x, y); started = true; }
			};
			for (let c = 0; c < d.cols; c++) { pt(c, d.first[c]); pt(c, d.min[c]); pt(c, d.max[c]); pt(c, d.last[c]); }
		} else {
			for (let i = 0; i < n; i++) { const x = xOf(cache.t[i]); const y = yOf(arr[i]); i ? g.lineTo(x, y) : g.moveTo(x, y); }
		}
		g.stroke();
	}
	g.globalAlpha = 1;
	return { ...base, lo, yr };
}

function draw() {
	const c = canvasEl.value;
	if (!c || !ctx) return;
	const CW = c.clientWidth, CH = c.clientHeight;
	if (CW === 0 || CH === 0) return;
	// The ratio the canvas was actually sized with (resize() set its backing store), not the live
	// devicePixelRatio: they differ after a DPR change that hasn't triggered a resize yet.
	const dpr = c.width / CW;
	const key = `${(props.channels ?? ['Fx', 'Fy', 'Fz']).join(',')}|${CW}x${CH}@${dpr}|${theme.value}|${props.cache.t.length}`;
	if (!layer || layer.cache !== props.cache || layer.key !== key) {
		const built = buildLayer(CW, CH, dpr);
		if (!built) return;
		built.key = key;
		layer = built;
	}
	const L = layer;
	lastT0 = L.t0; lastT1 = L.t1; lastW = L.W;
	// Blit in CSS pixels under the dpr transform, scaled to the CSS size: the layer is device-pixel
	// sized, so a devicePixelRatio change without a resize (window moved to another monitor) still
	// draws it at the right size until the next rebuild.
	ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
	ctx.drawImage(L.canvas, 0, 0, CW, CH);
	if (props.cache.t.length < 2) { lastHandles = null; return; }

	const span = Math.max(1e-3, L.t1 - L.t0);
	const xOf = (t: number) => ML + ((t - L.t0) / span) * L.W;
	// Cut window shading -- props override the cache's own auto-detected csSec/ceSec when given
	// (the save dialog's editable crop), otherwise this is exactly the old read-only display.
	const csSec = props.cropStartSec ?? props.cache.csSec;
	const ceSec = props.cropEndSec ?? props.cache.ceSec;
	if (ceSec > csSec) {
		ctx.fillStyle = 'rgba(74,222,128,0.06)';
		ctx.fillRect(xOf(csSec), MT, xOf(ceSec) - xOf(csSec), L.H);
	}

	if (props.cropEditable && ceSec > csSec) {
		lastHandles = { startX: xOf(csSec), endX: xOf(ceSec), top: MT, bottom: MT + L.H };
		for (const [x, col] of [[lastHandles.startX, '#0f766e'], [lastHandles.endX, '#b91c1c']] as const) {
			ctx.strokeStyle = col; ctx.lineWidth = 2;
			ctx.beginPath(); ctx.moveTo(x, MT); ctx.lineTo(x, MT + L.H); ctx.stroke();
		}
	} else {
		lastHandles = null;
	}
}

// Pointer events arrive faster than frames; coalesce every cause of a redraw to one per frame.
let raf = 0;
function scheduleDraw() {
	if (raf) return;
	raf = requestAnimationFrame(() => { raf = 0; draw(); });
}

watch(() => props.cache, () => scheduleDraw());
watch(() => props.channels, () => scheduleDraw());
watch(() => [props.cropStartSec, props.cropEndSec], () => scheduleDraw());
watch(theme, () => scheduleDraw());

onMounted(() => { resize(); window.addEventListener('resize', resize); ro = new ResizeObserver(resize); if (canvasEl.value) ro.observe(canvasEl.value); nextTick(resize); });
onBeforeUnmount(() => { window.removeEventListener('resize', resize); ro?.disconnect(); if (raf) cancelAnimationFrame(raf); });
</script>

<template>
	<div class="finished-force" :class="{ editable: cropEditable }">
		<canvas ref="canvasEl" @pointerdown="onPointerDown" @pointermove="onPointerMove" @pointerup="onPointerUp" @pointercancel="onPointerUp"></canvas>
		<div class="legend">
			<span v-for="k in (channels ?? ['Fx', 'Fy', 'Fz'])" :key="k" class="lg" :style="{ color: channelColor(k, theme) }">
				<i :style="{ background: channelColor(k, theme) }"></i>{{ k }}
			</span>
		</div>
	</div>
</template>

<style scoped>
.finished-force { position: relative; width: 100%; height: 100%; min-height: 160px; border-radius: 8px; overflow: hidden; background: var(--plot-bg); }
.finished-force canvas { width: 100%; height: 100%; display: block; }
.finished-force.editable canvas { cursor: ew-resize; }
.legend { position: absolute; top: 6px; right: 8px; display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 4px 8px; font-size: var(--fs-xs); font-weight: 600; max-width: 60%; padding: 2px 6px; border-radius: 6px; background: color-mix(in srgb, var(--plot-bg) 85%, transparent); }
.lg i { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 3px; vertical-align: middle; }
</style>
