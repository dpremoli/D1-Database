<script setup lang="ts">
// Canvas-2D polar (torque/force vs spindle angle) plot. Deliberately NOT WebGL: after
// striding, a polar view is thousands of points, not millions, and canvas makes the axis
// furniture (radial grid, spoke labels, colorbar) trivial. See
// docs/superpowers/specs/2026-09-07-milling-path-models-and-polar-design.md #6.
import { nextTick, onMounted, ref, watch } from 'vue';
import type { Cache } from './liveCache';
import { buildPolar, type PolarParams, type PolarResult } from './polar';
import { COLORMAPS } from './liveCloud';

const props = withDefaults(defineProps<{
	cache: Cache | null;
	params: PolarParams;
	colormap: string;
	pointSize: number;
	rMax?: number | null;
	paneLabel?: string;
	/** Number of cutting edges -- draws N equally-spaced spokes so a periodic signal's
	 * lobes are easy to eyeball against tooth count. 0 hides the spoke overlay. */
	flutes?: number;
}>(), { rMax: null, paneLabel: '', flutes: 0 });

const emit = defineEmits<{
	(e: 'loaded', v: { count: number; dropped: number; rMin: number; rMax: number }): void;
}>();

const canvasEl = ref<HTMLCanvasElement | null>(null);
const result = ref<PolarResult | null>(null);
const errorMsg = ref<string | null>(null);

function rebuild() {
	errorMsg.value = null;
	if (!props.cache) { result.value = null; draw(); return; }
	const r = buildPolar(props.cache, props.params);
	result.value = r;
	if (!r) {
		errorMsg.value = props.params.radius === 'Mz' ? 'no torque channel in this capture' : 'no data';
	} else {
		emit('loaded', { count: r.count, dropped: r.dropped, rMin: r.rMin, rMax: r.rMax });
	}
	draw();
}

function draw() {
	const canvas = canvasEl.value;
	if (!canvas) return;
	const rect = canvas.getBoundingClientRect();
	const dpr = Math.min(window.devicePixelRatio || 1, 2);
	const w = Math.max(1, rect.width), h = Math.max(1, rect.height);
	canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
	const g = canvas.getContext('2d');
	if (!g) return;
	g.setTransform(dpr, 0, 0, dpr, 0, 0);
	g.clearRect(0, 0, w, h);

	const cx = w / 2, cy = h / 2;
	const radiusPx = Math.min(w, h) / 2 - 28;
	const r = result.value;
	const rMax = props.rMax ?? (r ? r.rMax * 1.05 || 1 : 1);

	// radial grid: 4 rings + spokes every 30deg
	g.strokeStyle = 'rgba(148,163,184,0.35)'; g.fillStyle = 'rgba(148,163,184,0.7)';
	g.font = '10px sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
	for (let ring = 1; ring <= 4; ring++) {
		const rr = (radiusPx * ring) / 4;
		g.beginPath(); g.arc(cx, cy, rr, 0, Math.PI * 2); g.stroke();
	}
	for (let deg = 0; deg < 360; deg += 30) {
		const a = (deg * Math.PI) / 180;
		g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx + radiusPx * Math.cos(a), cy + radiusPx * Math.sin(a)); g.stroke();
	}

	// flute spokes, distinguishable from the 30deg grid
	if (props.flutes > 0) {
		g.strokeStyle = 'rgba(96,165,250,0.6)'; g.lineWidth = 1.5;
		for (let f = 0; f < props.flutes; f++) {
			const a = (f / props.flutes) * Math.PI * 2;
			g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx + radiusPx * Math.cos(a), cy + radiusPx * Math.sin(a)); g.stroke();
		}
		g.lineWidth = 1;
	}

	if (r && r.count > 0) {
		const cm = COLORMAPS[props.colormap] || COLORMAPS.viridis;
		const span = (r.rMax - r.rMin) || 1;
		for (let k = 0; k < r.count; k++) {
			const rr = Math.min(radiusPx, (r.r[k] / rMax) * radiusPx);
			const x = cx + rr * Math.cos(r.phi[k]), y = cy + rr * Math.sin(r.phi[k]);
			const [cr, cg, cb] = cm((r.r[k] - r.rMin) / span);
			g.fillStyle = `rgb(${Math.round(cr * 255)},${Math.round(cg * 255)},${Math.round(cb * 255)})`;
			g.beginPath(); g.arc(x, y, props.pointSize, 0, Math.PI * 2); g.fill();
		}
	}

	// footer: angle-source honesty label -- tacho vs atan2(Fy,Fx) is the difference between a
	// trustworthy plot and a suggestive one, and the viewer must not have to guess which.
	g.fillStyle = 'rgba(226,232,240,0.85)'; g.textAlign = 'left'; g.font = '11px sans-serif';
	const srcLabel = props.params.angle.source === 'tacho' ? 'angle: tacho'
		: props.params.angle.source === 'force_vector' ? 'angle: atan2(Fy,Fx)' : 'angle: index pulse';
	g.fillText(srcLabel, 8, h - 10);
	if (props.paneLabel) { g.textAlign = 'right'; g.fillText(props.paneLabel, w - 8, h - 10); }
}

watch(() => [props.cache, props.params, props.rMax, props.colormap, props.flutes], rebuild, { deep: true });
onMounted(() => { nextTick(rebuild); window.addEventListener('resize', draw); });
</script>

<template>
	<div class="polar-plot">
		<canvas ref="canvasEl" class="polar-canvas"></canvas>
		<div v-if="errorMsg" class="polar-empty">{{ errorMsg }}</div>
	</div>
</template>

<style scoped>
.polar-plot { position: relative; width: 100%; height: 100%; }
.polar-canvas { width: 100%; height: 100%; display: block; }
.polar-empty { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: var(--text-dim); font-size: 13px; pointer-events: none; }
</style>
