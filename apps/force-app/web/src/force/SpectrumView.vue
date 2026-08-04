<script setup lang="ts">
// Finished-cut spectral view for the plotting dashboard: fetches the STFT of one axis from the
// filter-service (/spectrogram) and renders it three ways — a time × frequency heatmap
// (spectrogram), recent spectra stacked with an offset (waterfall), or the time-averaged power
// spectrum (power, dB). Mirrors the live recording views so plotting stays at feature parity.
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { type FilterChain, fetchSpectrogram } from './filterChain';

const props = defineProps<{
	cacheFileId: string | null | undefined;
	chain: FilterChain;
	axis: string;
	mode: 'psd' | 'spectrogram' | 'waterfall';
	color?: string;
}>();

const canvasEl = ref<HTMLCanvasElement | null>(null);
let ctx: CanvasRenderingContext2D | null = null;
let ro: ResizeObserver | null = null;
const off = document.createElement('canvas');
const offCtx = off.getContext('2d');

type Grid = { f: number[]; t: number[]; S: number[][]; fmax: number };
const grid = ref<Grid | null>(null);
const loading = ref(false);
const err = ref<string | null>(null);
let reqId = 0;

async function load() {
	if (!props.cacheFileId) { grid.value = null; return; }
	const mine = ++reqId;
	loading.value = true; err.value = null;
	try {
		const g = await fetchSpectrogram(props.cacheFileId, props.chain, props.axis);
		if (mine === reqId) { grid.value = g; }
	} catch (e: any) {
		if (mine === reqId) { err.value = e?.message || 'spectrogram failed'; grid.value = null; }
	} finally {
		if (mine === reqId) { loading.value = false; draw(); }
	}
}

// dB (-80..0) → RGB, inferno-ish (dark → magenta → yellow).
function color(db: number, out: Uint8ClampedArray, o: number) {
	const x = Math.max(0, Math.min(1, (db + 80) / 80));
	out[o] = Math.round(255 * Math.min(1, Math.max(0, 1.6 * x - 0.35)));
	out[o + 1] = Math.round(255 * Math.min(1, Math.max(0, 1.7 * x - 0.6)));
	out[o + 2] = Math.round(255 * Math.min(1, Math.max(0, 1.1 - 1.8 * Math.abs(x - 0.4))));
	out[o + 3] = 255;
}

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
	const g = grid.value;
	if (loading.value && !g) return note('computing spectrum…');
	if (err.value) return note(err.value);
	if (!g || !g.S.length || !g.t.length) return note('no spectrum');

	const nF = g.f.length, nT = g.t.length;
	const stroke = props.color || '#38bdf8';

	if (props.mode === 'spectrogram') {
		if (!offCtx) return;
		off.width = nT; off.height = nF;
		const img = offCtx.createImageData(nT, nF);
		for (let fi = 0; fi < nF; fi++) {
			const row = g.S[fi];
			const y = nF - 1 - fi;                 // low freq at the bottom
			for (let ti = 0; ti < nT; ti++) color(row[ti], img.data, (y * nT + ti) * 4);
		}
		offCtx.putImageData(img, 0, 0);
		ctx.imageSmoothingEnabled = true;
		ctx.drawImage(off, 0, 0, nT, nF, 0, 0, W, H);
		label(`${props.axis} spectrogram`, stroke, W, H, g);
		return;
	}

	if (props.mode === 'psd') {
		// time-averaged spectrum (mean dB across time) → single line
		ctx.strokeStyle = stroke; ctx.lineWidth = 1.3; ctx.beginPath();
		for (let fi = 0; fi < nF; fi++) {
			let s = 0; const row = g.S[fi]; for (let ti = 0; ti < nT; ti++) s += row[ti];
			const db = s / nT;                     // -80..0
			const x = (fi / (nF - 1)) * (W - 8) + 4;
			const y = H - ((db + 80) / 80) * (H - 20) - 6;
			fi ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
		}
		ctx.stroke();
		label(`${props.axis} power (dB)`, stroke, W, H, g);
		return;
	}

	// waterfall: stack recent time columns as offset line spectra
	const MAX = 46;
	const cols: number[] = [];
	const stride = Math.max(1, Math.floor(nT / MAX));
	for (let ti = 0; ti < nT; ti += stride) cols.push(ti);
	const top = 18, bottom = H - 16, band = bottom - top, traceH = band * 0.34;
	for (let k = 0; k < cols.length; k++) {
		const ti = cols[k];
		const age = 1 - k / (cols.length - 1);     // newest (last) at the front/bottom
		const yBase = top + age * (band - traceH) + traceH;
		ctx.strokeStyle = stroke; ctx.globalAlpha = 0.25 + 0.75 * (1 - age); ctx.lineWidth = k === cols.length - 1 ? 1.5 : 1;
		ctx.beginPath();
		for (let fi = 0; fi < nF; fi++) {
			const db = g.S[fi][ti];
			const x = (fi / (nF - 1)) * (W - 8) + 4;
			const y = yBase - ((db + 80) / 80) * traceH;
			fi ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
		}
		ctx.stroke();
	}
	ctx.globalAlpha = 1;
	label(`${props.axis} waterfall`, stroke, W, H, g);
}

function note(msg: string) {
	if (!ctx) return;
	ctx.fillStyle = 'rgba(148,163,184,0.75)'; ctx.font = '12px system-ui';
	ctx.fillText(msg, 12, (canvasEl.value?.clientHeight || 40) / 2);
}
function label(text: string, col: string, W: number, H: number, g: Grid) {
	if (!ctx) return;
	ctx.fillStyle = col; ctx.font = '11px system-ui'; ctx.textAlign = 'left';
	ctx.fillText(text, 8, 14);
	ctx.fillStyle = 'rgba(226,232,240,0.55)'; ctx.textAlign = 'right';
	ctx.fillText(`${Math.round(g.fmax)} Hz`, W - 6, H - 5); ctx.textAlign = 'left';
}

const key = () => `${props.cacheFileId}|${props.axis}|${props.mode === 'spectrogram' ? 's' : props.mode}|${JSON.stringify(props.chain)}`;
watch(key, load);
onMounted(() => { load(); resize(); ro = new ResizeObserver(resize); if (canvasEl.value) ro.observe(canvasEl.value); });
onBeforeUnmount(() => ro?.disconnect());
</script>

<template>
	<div class="spec-view"><canvas ref="canvasEl"></canvas></div>
</template>

<style scoped>
.spec-view { width: 100%; height: 100%; min-height: 160px; border-radius: 8px; overflow: hidden; background: #0b1020; }
.spec-view canvas { width: 100%; height: 100%; display: block; }
</style>
