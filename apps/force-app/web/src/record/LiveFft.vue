<script setup lang="ts">
// Live amplitude spectrum: draws the backend's rolling Welch FFT of the selected axis. Canvas 2D,
// log-ish x is avoided for simplicity (linear Hz); redraws when a new fft frame arrives.
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import type { RecordClient } from './liveClient';

const props = defineProps<{ client: RecordClient }>();
const canvasEl = ref<HTMLCanvasElement | null>(null);
let ctx: CanvasRenderingContext2D | null = null;
let ro: ResizeObserver | null = null;

function resize() {
	const c = canvasEl.value; if (!c) return;
	const r = c.getBoundingClientRect();
	const dpr = Math.min(window.devicePixelRatio || 1, 2);
	c.width = Math.max(1, Math.floor(r.width * dpr));
	c.height = Math.max(1, Math.floor(r.height * dpr));
	ctx = c.getContext('2d');
	if (ctx) ctx.scale(dpr, dpr);
	draw();
}

function draw() {
	const c = canvasEl.value; if (!c || !ctx) return;
	const W = c.clientWidth, H = c.clientHeight;
	ctx.clearRect(0, 0, W, H);
	ctx.fillStyle = '#0b1020'; ctx.fillRect(0, 0, W, H);
	const fft = props.client.fft;
	ctx.strokeStyle = 'rgba(255,255,255,0.06)';
	for (let i = 1; i < 4; i++) { const y = (H * i) / 4; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
	if (!fft || fft.f.length < 2) {
		ctx.fillStyle = 'rgba(148,163,184,0.7)'; ctx.font = '12px system-ui';
		ctx.fillText('waiting for spectrum…', 12, H / 2);
		return;
	}
	const f = fft.f, amp = fft.amp;
	const fmax = f[f.length - 1] || 1;
	let amax = 0; for (const a of amp) if (a > amax) amax = a;
	amax = amax || 1;
	ctx.strokeStyle = '#38bdf8'; ctx.lineWidth = 1.2; ctx.beginPath();
	for (let i = 0; i < f.length; i++) {
		const x = (f[i] / fmax) * (W - 8) + 4;
		const y = H - (amp[i] / amax) * (H - 16) - 4;
		i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
	}
	ctx.stroke();
	ctx.fillStyle = 'rgba(226,232,240,0.75)'; ctx.font = '11px system-ui';
	ctx.fillText(`${fft.axis} spectrum`, 8, 14);
	ctx.fillText(`${Math.round(fmax)} Hz`, W - 52, H - 6);
}

watch(() => props.client.fftSeq.value, draw);
onMounted(() => { resize(); ro = new ResizeObserver(resize); if (canvasEl.value) ro.observe(canvasEl.value); });
onBeforeUnmount(() => ro?.disconnect());
</script>

<template>
	<div class="live-fft"><canvas ref="canvasEl"></canvas></div>
</template>

<style scoped>
.live-fft { width: 100%; height: 100%; min-height: 140px; border-radius: 8px; overflow: hidden; background: #0b1020; }
.live-fft canvas { width: 100%; height: 100%; display: block; }
</style>
