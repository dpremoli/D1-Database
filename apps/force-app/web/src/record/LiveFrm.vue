<script setup lang="ts">
// Live FRM fingerprint: a three.js point cloud that accumulates the spiral as frames arrive from
// the RecordClient. Preallocated buffers filled incrementally (partial GPU upload of only the new
// points each frame). Colour uses the plotting app's shared COLORMAPS (viridis by default),
// mapping each point's chosen-axis force symmetrically around zero by the running |c| max.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import * as THREE from 'three';
import type { RecordClient } from './liveClient';
import { COLORMAPS } from '../force/liveCloud';

const props = withDefaults(defineProps<{ client: RecordClient; diam: number; colormap?: string; pointSize?: number; pointStride?: number }>(), {
	colormap: 'viridis', pointSize: 1.8, pointStride: 1,
});

const canvasEl = ref<HTMLCanvasElement | null>(null);
// Matches RecordClient's own accumulator cap (liveClient.ts: `private cap = 2_000_000`) — this used
// to be capped lower at 1,000,000, so a long/dense cut whose live point count outgrew this buffer
// silently stopped rendering new points past it (TypedArray writes past the end are a silent
// no-op, not an error) while the accumulator kept counting fine. Sized for the worst case
// (pointStride=1); a stride > 1 just uploads fewer of the CAP slots.
const CAP = 2_000_000;
let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.OrthographicCamera | null = null;
let geom: THREE.BufferGeometry | null = null;
let posAttr: THREE.BufferAttribute | null = null;
let colAttr: THREE.BufferAttribute | null = null;
let mat: THREE.PointsMaterial | null = null;
let disc: THREE.CanvasTexture | null = null;
let raf = 0;
let uploaded = 0;   // source-side cursor into client.frm (every point seen, pre-decimation)
let rendered = 0;   // destination-side cursor into the GPU buffer (post-decimation)
let cssW = 1, cssH = 1;
let ro: ResizeObserver | null = null;
// tracked point bounds (mm) for auto-fit framing — robust for both sim and replayed real cuts
let bx0 = Infinity, bx1 = -Infinity, by0 = Infinity, by1 = -Infinity;

function makeDisc(): THREE.CanvasTexture {
	const s = 64, cv = document.createElement('canvas'); cv.width = cv.height = s;
	const c = cv.getContext('2d')!;
	c.beginPath(); c.arc(s / 2, s / 2, s / 2 - 2, 0, Math.PI * 2); c.fillStyle = '#fff'; c.fill();
	const t = new THREE.CanvasTexture(cv); t.needsUpdate = true; return t;
}

function setup() {
	const canvas = canvasEl.value!;
	renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
	renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
	renderer.setClearColor(0x000000, 0);
	scene = new THREE.Scene();
	camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 10);
	camera.position.set(0, 0, 5);
	geom = new THREE.BufferGeometry();
	posAttr = new THREE.BufferAttribute(new Float32Array(CAP * 3), 3);
	colAttr = new THREE.BufferAttribute(new Float32Array(CAP * 3), 3);
	posAttr.setUsage(THREE.DynamicDrawUsage); colAttr.setUsage(THREE.DynamicDrawUsage);
	geom.setAttribute('position', posAttr);
	geom.setAttribute('color', colAttr);
	geom.setDrawRange(0, 0);
	disc = makeDisc();
	mat = new THREE.PointsMaterial({ size: props.pointSize, sizeAttenuation: false, vertexColors: true, map: disc, alphaTest: 0.5, transparent: false });
	scene.add(new THREE.Points(geom, mat));
	sizeCanvas(); frame();
	loop();
}

function sizeCanvas() {
	const c = canvasEl.value; if (!c || !renderer) return;
	const r = c.getBoundingClientRect();
	cssW = Math.max(1, r.width); cssH = Math.max(1, r.height);
	renderer.setSize(cssW, cssH, false);
	frameCamera();
}

// Fit the orthographic camera to the actual point bounds (falls back to diam when empty).
function frameCamera() {
	if (!camera) return;
	const has = bx1 >= bx0;
	const cx = has ? (bx0 + bx1) / 2 : 0;
	const cy = has ? (by0 + by1) / 2 : 0;
	const span = has ? Math.max(bx1 - bx0, by1 - by0, 1) : props.diam;
	const half = (span * 1.12) / 2;
	const aspect = cssW / cssH;
	camera.left = cx - half * (aspect >= 1 ? aspect : 1);
	camera.right = cx + half * (aspect >= 1 ? aspect : 1);
	camera.top = cy + half / (aspect >= 1 ? 1 : aspect);
	camera.bottom = cy - half / (aspect >= 1 ? 1 : aspect);
	camera.position.set(cx, cy, 5);
	camera.updateProjectionMatrix();
}

function resetUpload() {
	uploaded = 0; rendered = 0;
	geom?.setDrawRange(0, 0);
	bx0 = by0 = Infinity; bx1 = by1 = -Infinity;
}

function frame() {
	const cm = COLORMAPS[props.colormap] || COLORMAPS.viridis;
	const fm = props.client.frm;
	// New run detected (buffers reset) -> clear our upload cursor + bounds.
	if (fm.count < uploaded) resetUpload();
	const from = uploaded, to = fm.count;
	if (to > from && posAttr && colAttr) {
		const cMax = Math.max(1e-6, fm.cAbsMax);
		const pos = posAttr.array as Float32Array;
		const col = colAttr.array as Float32Array;
		// pointStride thins the LIVE map by keeping every Nth accumulated point (indexed on the
		// absolute source index, so the kept subset is stable regardless of chunking) — this is
		// what lets a long/dense cut stay responsive and under the GPU buffer cap, independent of
		// the coarser decimation the backend already applies per-chunk.
		const stride = Math.max(1, Math.round(props.pointStride) || 1);
		const firstKept = from + ((stride - (from % stride)) % stride);
		for (let i = firstKept; i < to; i += stride) {
			const x = fm.xy[i * 2], y = fm.xy[i * 2 + 1];
			const w = rendered;
			if (w >= CAP) break;
			pos[w * 3] = x; pos[w * 3 + 1] = y; pos[w * 3 + 2] = 0;
			if (x < bx0) bx0 = x; if (x > bx1) bx1 = x; if (y < by0) by0 = y; if (y > by1) by1 = y;
			const tnorm = Math.min(1, Math.max(0, (fm.c[i] + cMax) / (2 * cMax)));
			const [r, g, b] = cm(tnorm);
			col[w * 3] = r; col[w * 3 + 1] = g; col[w * 3 + 2] = b;
			rendered++;
		}
		// Re-upload the attribute buffers (full upload — robust across three versions; point
		// counts in 2a are modest and this only runs on frames that actually added points).
		posAttr.needsUpdate = true; colAttr.needsUpdate = true;
		geom!.setDrawRange(0, rendered);
		uploaded = to;
	}
}

function loop() {
	raf = requestAnimationFrame(loop);
	frame();
	frameCamera();  // cheap; keeps the view fitted as the spiral grows
	if (mat && mat.size !== props.pointSize) mat.size = props.pointSize;
	if (renderer && scene && camera) renderer.render(scene, camera);
}

// Reactive point count for the label (client.frm.count is a plain field; frameSeq bumps per frame).
const ptsLabel = computed(() => { void props.client.frameSeq.value; return props.client.frm.count; });

watch(() => props.diam, () => sizeCanvas());
// Changing the decimation live re-renders the WHOLE accumulated spiral at the new density
// (not just future points) so the displayed map is consistent at a single stride throughout.
watch(() => props.pointStride, () => resetUpload());
onMounted(() => { setup(); window.addEventListener('resize', sizeCanvas); ro = new ResizeObserver(sizeCanvas); if (canvasEl.value) ro.observe(canvasEl.value); nextTick(sizeCanvas); });
onBeforeUnmount(() => {
	cancelAnimationFrame(raf);
	window.removeEventListener('resize', sizeCanvas);
	ro?.disconnect();
	geom?.dispose(); disc?.dispose();
	try { renderer?.forceContextLoss(); } catch { /* ignore */ }
	renderer?.dispose();
});
</script>

<template>
	<div class="live-frm">
		<canvas ref="canvasEl"></canvas>
		<span class="pts">{{ ptsLabel.toLocaleString() }} pts</span>
	</div>
</template>

<style scoped>
.live-frm { position: relative; width: 100%; height: 100%; min-height: 200px; border-radius: 8px; overflow: hidden; background: #0b1020; }
.live-frm canvas { width: 100%; height: 100%; display: block; }
.pts { position: absolute; right: 6px; bottom: 4px; font-size: 10px; color: rgba(255,255,255,0.6); font-variant-numeric: tabular-nums; }
</style>
