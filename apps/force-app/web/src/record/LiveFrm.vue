<script setup lang="ts">
// Live FRM fingerprint: a three.js point cloud that accumulates the spiral as frames arrive from
// the RecordClient. Preallocated buffers filled incrementally (partial GPU upload of only the new
// points each frame). Colour uses the plotting app's shared COLORMAPS (viridis by default),
// mapping each point's chosen-axis force symmetrically around zero by the running |c| max.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import * as THREE from 'three';
import type { RecordClient } from './liveClient';
import { COLORMAPS, type Axis } from '@d1/force-plotting';

const props = withDefaults(defineProps<{ client: RecordClient; diam: number; colormap?: string; pointSize?: number; pointStride?: number; axis?: Axis }>(), {
	colormap: 'viridis', pointSize: 1.8, pointStride: 1, axis: 'Fz',
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

// ---- View framing -------------------------------------------------------------------------
// The current framing in world units (mm): centre + half-height. Auto-fit recomputes these from
// the point bounds every frame; once the user pans/zooms, `userView` latches and auto-fit stops
// touching them (#52 — the view read as "locked" precisely because the per-frame re-fit stomped
// any attempt to move it). Reset View hands control back to auto-fit.
let viewCx = 0, viewCy = 0, viewHalf = 1;
const userView = ref(false);

function halfExtents() {
	const aspect = cssW / cssH;
	return { hw: viewHalf * (aspect >= 1 ? aspect : 1), hh: viewHalf / (aspect >= 1 ? 1 : aspect) };
}

function applyCamera() {
	if (!camera) return;
	const { hw, hh } = halfExtents();
	camera.left = viewCx - hw; camera.right = viewCx + hw;
	camera.top = viewCy + hh; camera.bottom = viewCy - hh;
	camera.position.set(viewCx, viewCy, 5);
	camera.updateProjectionMatrix();
}

// Fit to the actual point bounds (falls back to diam when empty), unless the user owns the view.
function frameCamera() {
	if (!camera) return;
	if (!userView.value) {
		const has = bx1 >= bx0;
		viewCx = has ? (bx0 + bx1) / 2 : 0;
		viewCy = has ? (by0 + by1) / 2 : 0;
		const span = has ? Math.max(bx1 - bx0, by1 - by0, 1) : props.diam;
		viewHalf = (span * 1.12) / 2;
	}
	applyCamera();
}

function resetView() { userView.value = false; frameCamera(); }

// ---- Pan / zoom ---------------------------------------------------------------------------
// Hand-rolled against the orthographic camera rather than OrbitControls: this is a flat XY
// fingerprint map, so orbiting has no meaning here — only pan and zoom do, and OrbitControls
// would additionally fight the auto-fit above for ownership of the camera each frame.
const MIN_HALF = 0.05;            // mm — stop zooming in once a single point fills the panel
const ZOOM_OUT_FACTOR = 20;       // relative to the auto-fit span, so "way out" is still bounded

function worldAt(ev: { clientX: number; clientY: number }) {
	const c = canvasEl.value!;
	const r = c.getBoundingClientRect();
	const { hw, hh } = halfExtents();
	return {
		x: viewCx - hw + ((ev.clientX - r.left) / r.width) * 2 * hw,
		y: viewCy + hh - ((ev.clientY - r.top) / r.height) * 2 * hh,
	};
}

function onWheel(ev: WheelEvent) {
	const before = worldAt(ev);
	userView.value = true;
	const span = bx1 >= bx0 ? Math.max(bx1 - bx0, by1 - by0, 1) : props.diam;
	const maxHalf = (span * 1.12) / 2 * ZOOM_OUT_FACTOR;
	viewHalf = Math.min(maxHalf, Math.max(MIN_HALF, viewHalf * Math.exp(ev.deltaY * 0.0015)));
	// Keep the point under the cursor pinned while the scale changes.
	const after = worldAt(ev);
	viewCx += before.x - after.x;
	viewCy += before.y - after.y;
	applyCamera();
}

const dragging = ref(false);
let lastX = 0, lastY = 0;
function onPointerDown(ev: PointerEvent) {
	if (ev.button !== 0) return;
	dragging.value = true; lastX = ev.clientX; lastY = ev.clientY;
	canvasEl.value?.setPointerCapture(ev.pointerId);
}
function onPointerMove(ev: PointerEvent) {
	if (!dragging.value) return;
	const c = canvasEl.value; if (!c) return;
	const r = c.getBoundingClientRect();
	const { hw, hh } = halfExtents();
	userView.value = true;
	viewCx -= ((ev.clientX - lastX) / r.width) * 2 * hw;
	viewCy += ((ev.clientY - lastY) / r.height) * 2 * hh;
	lastX = ev.clientX; lastY = ev.clientY;
	applyCamera();
}
function onPointerUp(ev: PointerEvent) {
	if (!dragging.value) return;
	dragging.value = false;
	canvasEl.value?.releasePointerCapture?.(ev.pointerId);
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
		// Prefer the percentile-based cLo/cHi playback sets at load time (matches the finished-cut
		// view's own colour scale exactly, computed once over the whole cut). A true live recording
		// never sets these — it can't know its final range while still acquiring — so it falls back
		// to the running |max|, symmetric about zero.
		const axisMax = fm.cAbsMaxByAxis[props.axis];
		const haveRange = fm.cHi !== undefined && fm.cLo !== undefined && fm.cHi > fm.cLo;
		const cLo = haveRange ? fm.cLo! : -Math.max(1e-6, axisMax);
		const cSpan = haveRange ? (fm.cHi! - fm.cLo!) : 2 * Math.max(1e-6, axisMax);
		const cArr = props.axis === 'Fx' ? fm.cx : props.axis === 'Fy' ? fm.cy : fm.cz;
		const pos = posAttr.array as Float32Array;
		const col = colAttr.array as Float32Array;
		// pointStride thins the LIVE map by keeping every Nth accumulated point (indexed on the
		// absolute source index, so the kept subset is stable regardless of chunking) — this is
		// what lets a long/dense cut stay responsive and under the GPU buffer cap, independent of
		// the coarser decimation the backend already applies per-chunk.
		const stride = Math.max(1, Math.round(props.pointStride) || 1);
		const firstKept = from + ((stride - (from % stride)) % stride);
		const writeStart = rendered;
		for (let i = firstKept; i < to; i += stride) {
			const x = fm.xy[i * 2], y = fm.xy[i * 2 + 1];
			const w = rendered;
			if (w >= CAP) break;
			pos[w * 3] = x; pos[w * 3 + 1] = y; pos[w * 3 + 2] = 0;
			if (x < bx0) bx0 = x; if (x > bx1) bx1 = x; if (y < by0) by0 = y; if (y > by1) by1 = y;
			const tnorm = Math.min(1, Math.max(0, (cArr[i] - cLo) / cSpan));
			const [r, g, b] = cm(tnorm);
			col[w * 3] = r; col[w * 3 + 1] = g; col[w * 3 + 2] = b;
			rendered++;
		}
		// Only re-upload the newly-written slice, not the whole CAP-sized buffer — a plain
		// needsUpdate=true (default updateRange covers the entire array) re-transfers the full
		// 2M-point buffer to the GPU on every frame that adds even one point, which is what made
		// long replays/recordings visibly stutter as the spiral grew. addUpdateRange restricts the
		// upload to [writeStart, rendered) so transfer cost stays proportional to new points only.
		if (rendered > writeStart) {
			posAttr.clearUpdateRanges(); colAttr.clearUpdateRanges();
			posAttr.addUpdateRange(writeStart * 3, (rendered - writeStart) * 3);
			colAttr.addUpdateRange(writeStart * 3, (rendered - writeStart) * 3);
			posAttr.needsUpdate = true; colAttr.needsUpdate = true;
		}
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
// Switching axis must recolour the entire accumulated spiral (all cx/cy/cz are already
// resident client-side), not just future points — same rebuild as a stride change.
watch(() => props.axis, () => resetUpload());
// #65: colour is baked into the GPU buffer at upload time, so without this a colormap change only
// tinted points appended AFTER it — the already-drawn spiral kept the old map until something else
// forced a full re-upload (navigating away and back remounted the component, which is exactly why
// the round trip appeared to "fix" it). Same whole-spiral rebuild as an axis change.
watch(() => props.colormap, () => resetUpload());
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
		<canvas
			ref="canvasEl"
			:class="{ grabbing: dragging }"
			@wheel.prevent="onWheel"
			@pointerdown="onPointerDown"
			@pointermove="onPointerMove"
			@pointerup="onPointerUp"
			@pointercancel="onPointerUp"
			@dblclick="resetView"
		></canvas>
		<!-- Only offered once the user has actually moved the view: until then auto-fit IS the
		     reset state, so the button would do nothing. Doubles as the discoverability cue that
		     the map is pannable at all. -->
		<button v-if="userView" class="reset-view" title="Back to auto-fit (or double-click the map)" @click="resetView">
			<span class="material-symbols-rounded">recenter</span> Reset view
		</button>
		<span class="pts">{{ ptsLabel.toLocaleString() }} pts</span>
	</div>
</template>

<style scoped>
.live-frm { position: relative; width: 100%; height: 100%; min-height: 200px; border-radius: 8px; overflow: hidden; background: var(--plot-bg); }
.live-frm canvas { width: 100%; height: 100%; display: block; cursor: grab; touch-action: none; }
.live-frm canvas.grabbing { cursor: grabbing; }
.reset-view {
	position: absolute; left: 6px; bottom: 4px;
	display: inline-flex; align-items: center; gap: 3px;
	padding: 2px 7px 2px 5px; font-size: 10px; line-height: 1.6;
	color: var(--text); background: var(--bg-2); border: 1px solid var(--border);
	border-radius: 999px; cursor: pointer; opacity: 0.85;
}
.reset-view:hover { opacity: 1; }
.reset-view .material-symbols-rounded { font-size: 13px; }
.pts { position: absolute; right: 6px; bottom: 4px; font-size: 10px; color: var(--text-dim); font-variant-numeric: tabular-nums; }
</style>
