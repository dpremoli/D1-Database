<script setup lang="ts">
// Live spectrum: draws the backend's rolling Welch spectra — one line per selected channel (summed
// Fx/Fy/Fz and/or the dyno sub-channels), just like the force plot draws a band per channel.
// `scale='psd'` shows a power spectrum in dB (0 dB at the peak); `scale='amp'` is linear amplitude.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import type { RecordClient } from './liveClient';
import { CH_COLOR } from './types';

const props = defineProps<{ client: RecordClient; channels?: string[]; scale?: 'amp' | 'psd' }>();
const canvasEl = ref<HTMLCanvasElement | null>(null);
let ctx: CanvasRenderingContext2D | null = null;
let ro: ResizeObserver | null = null;

// Channels to draw: the panel's selection, falling back to the backend's default axis.
const chans = computed(() => {
	const fft = props.client.fft;
	const avail = fft ? Object.keys(fft.spectra) : [];
	const sel = (props.channels && props.channels.length ? props.channels : [fft?.axis || 'Fz']).filter((c) => avail.includes(c));
	return sel.length ? sel : avail.slice(0, 1);
});

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
	ctx.strokeStyle = 'rgba(255,255,255,0.06)';
	for (let i = 1; i < 4; i++) { const y = (H * i) / 4; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }

	const fft = props.client.fft;
	const f = fft?.f;
	if (!fft || !f || f.length < 2) {
		ctx.fillStyle = 'rgba(148,163,184,0.7)'; ctx.font = '12px system-ui';
		ctx.fillText('waiting for spectrum…', 12, H / 2);
		return;
	}
	const fmax = f[f.length - 1] || 1;
	const psd = props.scale === 'psd';
	const drawn = chans.value;

	// Shared vertical scale across channels so amplitudes are comparable.
	let amax = 1e-9;
	for (const ch of drawn) { const s = fft.spectra[ch]; if (s) for (const a of s) if (a > amax) amax = a; }
	const floorDb = -60;
	const yOf = (a: number) => {
		if (psd) {
			const db = 20 * Math.log10((a || 1e-12) / amax); // 0 dB at peak
			const n = Math.max(0, Math.min(1, (db - floorDb) / -floorDb));
			return H - n * (H - 16) - 4;
		}
		return H - (a / amax) * (H - 16) - 4;
	};

	for (const ch of drawn) {
		const s = fft.spectra[ch]; if (!s) continue;
		ctx.strokeStyle = CH_COLOR[ch] || '#38bdf8'; ctx.lineWidth = 1.2; ctx.beginPath();
		for (let i = 0; i < f.length && i < s.length; i++) {
			const x = (f[i] / fmax) * (W - 8) + 4;
			const y = yOf(s[i]);
			i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
		}
		ctx.stroke();
	}

	// Legend + axis labels.
	ctx.font = '11px system-ui'; ctx.textAlign = 'left';
	let lx = 8;
	for (const ch of drawn) {
		ctx.fillStyle = CH_COLOR[ch] || '#38bdf8';
		ctx.fillText(ch, lx, 14); lx += ctx.measureText(ch).width + 12;
	}
	ctx.fillStyle = 'rgba(226,232,240,0.6)';
	ctx.fillText(psd ? 'power (dB)' : 'amplitude', 8, H - 6);
	ctx.textAlign = 'right'; ctx.fillText(`${Math.round(fmax)} Hz`, W - 6, H - 6); ctx.textAlign = 'left';
}

watch(() => props.client.fftSeq.value, draw);
watch(() => props.scale, draw);
watch(chans, draw, { deep: true });
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
