<script setup lang="ts">
// Rolling live force scope: draws the Fx/Fy/Fz min/max envelope over the last windowSec, from the
// RecordClient's trace buffer. Canvas 2D + rAF; autoscales Y to the visible window. Not reactive
// per-sample — it reads the plain buffers each frame.
import { onBeforeUnmount, onMounted, ref } from 'vue';
import type { RecordClient } from './liveClient';
import { AXIS_COLOR } from './types';

const props = defineProps<{ client: RecordClient }>();
const canvasEl = ref<HTMLCanvasElement | null>(null);
let raf = 0;
let ctx: CanvasRenderingContext2D | null = null;
let ro: ResizeObserver | null = null;

function resize() {
	const c = canvasEl.value;
	if (!c) return;
	const r = c.getBoundingClientRect();
	const dpr = Math.min(window.devicePixelRatio || 1, 2);
	c.width = Math.max(1, Math.floor(r.width * dpr));
	c.height = Math.max(1, Math.floor(r.height * dpr));
	ctx = c.getContext('2d');
	if (ctx) ctx.scale(dpr, dpr);
}

function draw() {
	raf = requestAnimationFrame(draw);
	const c = canvasEl.value;
	if (!c || !ctx) return;
	const W = c.clientWidth, H = c.clientHeight;
	ctx.clearRect(0, 0, W, H);
	ctx.fillStyle = '#0b1020';
	ctx.fillRect(0, 0, W, H);

	const tr = props.client.trace;
	const n = tr.t.length;
	if (n < 2) { drawGrid(W, H, 1); return; }

	const t0 = tr.t[0], t1 = tr.t[n - 1];
	const span = Math.max(1e-3, t1 - t0);
	// Y range across all axes in the window
	let lo = Infinity, hi = -Infinity;
	for (const arr of [tr.fx, tr.fy, tr.fz]) for (const [mn, mx] of arr) { if (mn < lo) lo = mn; if (mx > hi) hi = mx; }
	if (!isFinite(lo) || !isFinite(hi)) { lo = -1; hi = 1; }
	const pad = 0.1 * (hi - lo || 1);
	lo -= pad; hi += pad;
	const yr = hi - lo || 1;

	drawGrid(W, H, 1);
	const xOf = (t: number) => ((t - t0) / span) * (W - 8) + 4;
	const yOf = (v: number) => H - ((v - lo) / yr) * (H - 8) - 4;

	for (const [axis, arr] of [['Fx', tr.fx], ['Fy', tr.fy], ['Fz', tr.fz]] as const) {
		ctx.strokeStyle = AXIS_COLOR[axis];
		ctx.globalAlpha = 0.95;
		ctx.lineWidth = 1;
		// max line
		ctx.beginPath();
		for (let i = 0; i < n; i++) { const x = xOf(tr.t[i]); const y = yOf(arr[i][1]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
		ctx.stroke();
		// min line, lighter
		ctx.globalAlpha = 0.5;
		ctx.beginPath();
		for (let i = 0; i < n; i++) { const x = xOf(tr.t[i]); const y = yOf(arr[i][0]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
		ctx.stroke();
	}
	ctx.globalAlpha = 1;
	// zero line
	if (lo < 0 && hi > 0) { ctx.strokeStyle = 'rgba(255,255,255,0.18)'; ctx.beginPath(); ctx.moveTo(4, yOf(0)); ctx.lineTo(W - 4, yOf(0)); ctx.stroke(); }
	// labels
	ctx.fillStyle = 'rgba(226,232,240,0.75)';
	ctx.font = '11px system-ui';
	ctx.fillText(`${hi.toFixed(0)} N`, 6, 14);
	ctx.fillText(`${lo.toFixed(0)} N`, 6, H - 6);
}

function drawGrid(W: number, H: number, _n: number) {
	if (!ctx) return;
	ctx.strokeStyle = 'rgba(255,255,255,0.06)';
	ctx.lineWidth = 1;
	for (let i = 1; i < 4; i++) { const y = (H * i) / 4; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
}

onMounted(() => { resize(); window.addEventListener('resize', resize); ro = new ResizeObserver(resize); if (canvasEl.value) ro.observe(canvasEl.value); draw(); });
onBeforeUnmount(() => { cancelAnimationFrame(raf); window.removeEventListener('resize', resize); ro?.disconnect(); });
</script>

<template>
	<div class="live-force">
		<canvas ref="canvasEl"></canvas>
		<div class="legend">
			<span class="lg fx">Fx</span><span class="lg fy">Fy</span><span class="lg fz">Fz</span>
		</div>
	</div>
</template>

<style scoped>
.live-force { position: relative; width: 100%; height: 100%; min-height: 160px; border-radius: 8px; overflow: hidden; background: #0b1020; }
.live-force canvas { width: 100%; height: 100%; display: block; }
.legend { position: absolute; top: 6px; right: 8px; display: flex; gap: 8px; font-size: 11px; font-weight: 600; }
.lg::before { content: ''; display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 3px; vertical-align: middle; }
.lg.fx { color: #f87171; } .lg.fx::before { background: #dc2626; }
.lg.fy { color: #4ade80; } .lg.fy::before { background: #16a34a; }
.lg.fz { color: #60a5fa; } .lg.fz::before { background: #2563eb; }
</style>
