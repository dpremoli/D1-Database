<script setup lang="ts">
/*
 * Live FRM point cloud — a thin WebGL renderer that replaces the static FRM PNG in
 * the dashboard's FRM column when Live mode is on. It downloads the point-cloud cache
 * (live_cache.bin) once via the module-singleton LRU (liveCache.ts), then draws the
 * spiral fingerprint for the CURRENT geometry props (crop / Feed / Diameter / speed
 * model) recomputed client-side by buildCloud (liveCloud.ts). All plotting state lives
 * in the parent (ForceDashboard); the interactive VIEW (zoom/pan/rect-zoom) is local to
 * this renderer since it's purely a display transform over the same cloud.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useApi } from '@directus/extensions-sdk';
import * as THREE from 'three';
import { type Cache, cacheGet, cachePut, parseCache } from './liveCache';
import { type Axis, type Cloud, type SpeedMode, buildCloud, COLORMAPS } from './liveCloud';

const props = defineProps<{
	cacheFileId: string;
	axis: Axis;
	feed: number;
	diam: number;
	speedMode: SpeedMode;
	rpm: number;
	vc: number;
	timeScale: number;
	ppr: number;
	cropStartSec: number;
	cropEndSec: number;
	stride: number;
	gridding: boolean;
	gridN: number;
	pointSize: number;
	colormap: string;
	cmin?: number | null;
	cmax?: number | null;
}>();
const emit = defineEmits<{
	(e: 'loaded', meta: { csSec: number; ceSec: number; feed: number; diam: number; rpm: number; Fs: number; N: number }): void;
	(e: 'climits', v: { cmin: number; cmax: number }): void;
	(e: 'points', n: number): void;   // rendered point count (for the resolution readout)
}>();

const api = useApi();
const loading = ref(true);
const error = ref<string | null>(null);
const cache = ref<Cache | null>(null);
const pointCount = ref(0);
// Declared up here (not next to scheduleDraw) because the cacheFileId watch below runs
// load() with immediate:true; when the cache is already in the LRU (precached), load()
// runs synchronously during setup and calls resetView()->scheduleDraw(), which reads
// these — so they must be initialised first (else a "Cannot access 'raf'…" TDZ error).
let raf = 0;
let pendingRebuild = false;

async function load(id: string) {
	loading.value = true; error.value = null;
	try {
		let c = cacheGet(id);
		if (!c) {
			const res = await api.get(`/assets/${id}`, { responseType: 'arraybuffer' });
			c = parseCache(res.data as ArrayBuffer);
			cachePut(id, c);
		}
		cache.value = c;
		emit('loaded', {
			csSec: c.csSec, ceSec: c.ceSec, feed: c.feed, diam: c.diam,
			rpm: Math.round(c.rpm[c.rpm.length - 1] || 1000), Fs: c.Fs, N: c.N,
		});
		resetView();
		nextTick(() => { setupRenderer(); scheduleRebuild(); });
	} catch (e: any) {
		error.value = e?.message || 'failed to load live cache';
		cache.value = null;
	} finally {
		loading.value = false;
	}
}
watch(() => props.cacheFileId, (id) => { if (id) load(id); }, { immediate: true });

// ---- interactive view transform (equal-aspect, world = mm) ---------------------
// The view is a square-ish window on the world, expressed as centre + span (one
// span, since aspect is kept equal). viewActive=false means "auto-fit to data",
// recomputed every draw; any zoom/pan/rect-zoom switches it on. Reset returns to fit.
const viewActive = ref(false);
const vCx = ref(0), vCy = ref(0), vSpan = ref(1);
// updated each draw so the pointer handlers can map screen<->world
let fitCx = 0, fitCy = 0, fitSpan = 1, cssW = 1, cssH = 1;
const zoomed = computed(() => viewActive.value);

function resetView() { viewActive.value = false; scheduleDraw(); }
function effView() {
	return viewActive.value
		? { cx: vCx.value, cy: vCy.value, span: vSpan.value }
		: { cx: fitCx, cy: fitCy, span: fitSpan };
}
function scaleFor(span: number) {
	const s = (2 * 0.9) / (span || 1);
	const aspect = cssW / cssH;
	return aspect >= 1 ? { sx: s / aspect, sy: s } : { sx: s, sy: s * aspect };
}
// CSS-pixel (relative to canvas) -> world mm, under the current effective view
function screenToWorld(px: number, py: number) {
	const v = effView();
	const { sx, sy } = scaleFor(v.span);
	const offX = -v.cx * sx, offY = -v.cy * sy;
	const ndcX = (px / cssW) * 2 - 1, ndcY = 1 - (py / cssH) * 2;
	return { x: (ndcX - offX) / sx, y: (ndcY - offY) / sy, ndcX, ndcY, sx, sy };
}

// ---- overlays: colorbar + scale bar (reactive, refreshed each draw) ----
const climits = ref<{ cmin: number; cmax: number } | null>(null);
const scaleBar = ref<{ px: number; label: string } | null>(null);
const rampCss = computed(() => {
	const cm = COLORMAPS[props.colormap] || COLORMAPS.viridis;
	const stops: string[] = [];
	for (let i = 0; i <= 10; i++) {
		const [r, g, b] = cm(i / 10);
		stops.push(`rgb(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(b * 255)}) ${i * 10}%`);
	}
	return `linear-gradient(to top, ${stops.join(', ')})`;
});
function fmtN(v: number): string {
	const a = Math.abs(v);
	if (a >= 1000) return (v / 1000).toFixed(1) + 'k';
	if (a >= 100) return v.toFixed(0);
	if (a >= 10) return v.toFixed(1);
	return v.toFixed(2);
}
function updateScaleBar() {
	const v = effView();
	const { sx } = scaleFor(v.span);
	const pxPerMm = (sx * cssW) / 2;                 // world(mm) -> css px
	if (!(pxPerMm > 0) || !isFinite(pxPerMm)) { scaleBar.value = null; return; }
	const targetPx = 90;
	const cands = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500];
	let mm = cands[0];
	for (const c of cands) { if (c * pxPerMm <= Math.min(targetPx, cssW * 0.42)) mm = c; }
	scaleBar.value = { px: Math.round(mm * pxPerMm), label: mm >= 1 ? `${mm} mm` : `${mm * 1000} µm` };
}

// ---- three.js point renderer ----
// three.js is the unified renderer stack (Phase 1): it draws the ≤3M full-resolution
// cloud directly here, and Phase 2's Potree octree LOD will drop into this same scene.
// The 2D orthographic camera is driven by the EXISTING view math (scaleFor/effView) so
// pointer interaction (pan/zoom/rect-zoom) and the scale bar stay pixel-consistent with
// the render — only the GL core changed, not the interaction model.
const canvasEl = ref<HTMLCanvasElement | null>(null);
let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.OrthographicCamera | null = null;
let pointsGeom: THREE.BufferGeometry | null = null;
let pointsMat: THREE.PointsMaterial | null = null;
let discTex: THREE.CanvasTexture | null = null;
let ready = false;

// a soft white disc so points render as filled circles (matching the old fragment
// shader's round-point discard), not squares. alphaTest keeps them crisp + opaque.
function makeDisc(): THREE.CanvasTexture {
	const s = 64, cv = document.createElement('canvas'); cv.width = cv.height = s;
	const ctx = cv.getContext('2d')!;
	ctx.beginPath(); ctx.arc(s / 2, s / 2, s / 2 - 2, 0, Math.PI * 2); ctx.fillStyle = '#fff'; ctx.fill();
	const t = new THREE.CanvasTexture(cv); t.needsUpdate = true; return t;
}

function setupRenderer() {
	if (ready || !canvasEl.value) return;
	const canvas = canvasEl.value;
	try {
		renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true });
	} catch { error.value = 'WebGL unavailable in this browser'; return; }
	renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
	renderer.setClearColor(0x000000, 0);
	scene = new THREE.Scene();
	camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 1000);
	camera.position.set(0, 0, 10);
	discTex = makeDisc();
	pointsGeom = new THREE.BufferGeometry();
	pointsMat = new THREE.PointsMaterial({ size: 1.4, sizeAttenuation: false, vertexColors: true, map: discTex, alphaTest: 0.5, transparent: false });
	scene.add(new THREE.Points(pointsGeom, pointsMat));
	canvas.addEventListener('webglcontextlost', (e) => { e.preventDefault(); error.value = 'WebGL context lost — toggle Live to reload'; ready = false; });
	ready = true;
	if (ro) ro.observe(canvas);
}

function sizeCanvas(canvas: HTMLCanvasElement) {
	const r = canvas.getBoundingClientRect();
	cssW = Math.max(1, r.width); cssH = Math.max(1, r.height);
	renderer?.setSize(cssW, cssH, false);   // three manages the drawing-buffer size + pixel ratio
}

// The built cloud is the ONLY thing that depends on geometry/colour props. It is
// rebuilt (and re-uploaded to the GPU) only when one of those changes — NOT on
// pan/zoom/resize, which are pure view transforms handled by uniforms in draw().
// This is the core perf fix: dragging a million-point plot no longer re-runs the
// O(N) recompute + percentile sort + full buffer re-upload on every frame.
let cloud: Cloud | null = null;

function rebuild() {
	if (!ready || !pointsGeom || !canvasEl.value || !cache.value) return;
	cloud = buildCloud(cache.value, {
		axis: props.axis, feed: props.feed, diam: props.diam,
		speedMode: props.speedMode, rpm: props.rpm, vc: props.vc, timeScale: props.timeScale, ppr: props.ppr,
		cropStartSec: props.cropStartSec, cropEndSec: props.cropEndSec,
		stride: props.stride, gridding: props.gridding, gridN: props.gridN,
		colormap: COLORMAPS[props.colormap] || COLORMAPS.viridis,
		cmin: props.cmin, cmax: props.cmax,
	});
	pointCount.value = cloud?.count ?? 0;
	emit('points', pointCount.value);
	if (!cloud) { climits.value = null; scaleBar.value = null; return; }

	// data-fit params (used when the view is in auto-fit mode + as reset target)
	fitCx = (cloud.minX + cloud.maxX) / 2; fitCy = (cloud.minY + cloud.maxY) / 2;
	fitSpan = Math.max(cloud.maxX - cloud.minX, cloud.maxY - cloud.minY) || 1;

	// upload ONCE per rebuild. three needs 3-component positions; expand the 2D cloud
	// (z=0). Colours are already 3-component (0..1) → vertex colours.
	const n = cloud.count;
	const pos3 = new Float32Array(n * 3);
	for (let k = 0; k < n; k++) { pos3[k * 3] = cloud.pos[k * 2]; pos3[k * 3 + 1] = cloud.pos[k * 2 + 1]; }
	pointsGeom.setAttribute('position', new THREE.BufferAttribute(pos3, 3));
	pointsGeom.setAttribute('color', new THREE.BufferAttribute(cloud.col, 3));
	pointsGeom.setDrawRange(0, n);

	// colorbar limits (only changes with the cloud)
	const cl = { cmin: cloud.cmin, cmax: cloud.cmax };
	if (!climits.value || climits.value.cmin !== cl.cmin || climits.value.cmax !== cl.cmax) {
		climits.value = cl; emit('climits', cl);
	}
}

// View-only redraw: no recompute, no re-upload — just drive the orthographic camera
// from the current view and render the resident geometry. Cheap enough per frame.
function draw() {
	if (!ready || !renderer || !scene || !camera || !canvasEl.value || !cloud) return;
	sizeCanvas(canvasEl.value);
	const v = effView();
	// scaleFor maps world→NDC as ndc = (world-centre)*s; the ortho half-extents are
	// therefore 1/s, so the camera frustum reproduces the exact same mapping the pointer
	// math (screenToWorld) uses — keeping interaction and render perfectly aligned.
	const { sx, sy } = scaleFor(v.span);
	camera.left = -1 / sx; camera.right = 1 / sx;
	camera.top = 1 / sy; camera.bottom = -1 / sy;
	camera.position.set(v.cx, v.cy, 10);
	camera.updateProjectionMatrix();
	if (pointsMat) pointsMat.size = Math.max(1, props.pointSize || 1.4);
	renderer.render(scene, camera);

	updateScaleBar();
}

function scheduleDraw() {
	if (raf) return;
	raf = requestAnimationFrame(() => {
		raf = 0;
		if (pendingRebuild) { pendingRebuild = false; rebuild(); }
		draw();
	});
}
// Coalesce a rebuild into the next frame (geometry/colour change).
function scheduleRebuild() { pendingRebuild = true; scheduleDraw(); }

// Current visible world rectangle (mm) — the same (cx±1/sx, cy±1/sy) extents the
// camera renders — so the parent can ask the host to re-render exactly this viewport
// at full resolution for a pixel-identical download.
function currentBounds(): { xmin: number; xmax: number; ymin: number; ymax: number } {
	const v = effView();
	const { sx, sy } = scaleFor(v.span);
	return { xmin: v.cx - 1 / sx, xmax: v.cx + 1 / sx, ymin: v.cy - 1 / sy, ymax: v.cy + 1 / sy };
}
defineExpose({ currentBounds });

let ro: ResizeObserver | undefined;
onMounted(() => { ro = new ResizeObserver(() => scheduleDraw()); if (cache.value) nextTick(() => { setupRenderer(); scheduleRebuild(); }); });
onBeforeUnmount(() => {
	if (raf) cancelAnimationFrame(raf);
	ro?.disconnect();
	pointsGeom?.dispose(); pointsMat?.dispose(); discTex?.dispose(); renderer?.dispose();
});

// Geometry/colour props → rebuild the cloud. pointSize is view-only (a uniform), so
// it only needs a redraw.
watch(() => [props.axis, props.feed, props.diam, props.speedMode, props.rpm, props.vc, props.timeScale, props.ppr,
	props.cropStartSec, props.cropEndSec, props.stride, props.gridding, props.gridN,
	props.colormap, props.cmin, props.cmax], scheduleRebuild);
watch(() => props.pointSize, scheduleDraw);

// ---- pointer interaction: wheel-zoom, drag-pan, rectangular zoom ----
const rectTool = ref(false);                       // when on, drag draws a zoom rectangle
const rectSel = ref<{ x: number; y: number; w: number; h: number } | null>(null);
let panning = false, rectDrag = false;
let startPx = 0, startPy = 0;
let grab: { x: number; y: number } | null = null;   // world point grabbed for pan

function localXY(ev: PointerEvent | WheelEvent) {
	const r = canvasEl.value!.getBoundingClientRect();
	return { px: (ev as any).clientX - r.left, py: (ev as any).clientY - r.top };
}
function onWheel(ev: WheelEvent) {
	if (!cache.value) return;
	ev.preventDefault();
	const { px, py } = localXY(ev);
	const w = screenToWorld(px, py);
	const f = ev.deltaY < 0 ? 1.2 : 1 / 1.2;
	const v = effView();
	const newSpan = Math.min(fitSpan * 8, Math.max(fitSpan / 500, v.span / f));
	const { sx, sy } = scaleFor(newSpan);
	vCx.value = w.x - w.ndcX / sx;
	vCy.value = w.y - w.ndcY / sy;
	vSpan.value = newSpan;
	viewActive.value = true;
	scheduleDraw();
}
function onDown(ev: PointerEvent) {
	if (!cache.value) return;
	const { px, py } = localXY(ev);
	(ev.currentTarget as Element).setPointerCapture(ev.pointerId);
	if (rectTool.value) {
		rectDrag = true; startPx = px; startPy = py; rectSel.value = { x: px, y: py, w: 0, h: 0 };
	} else {
		panning = true; grab = { x: screenToWorld(px, py).x, y: screenToWorld(px, py).y };
		// activate the view (seed from fit) so panning has somewhere to write
		if (!viewActive.value) { vCx.value = fitCx; vCy.value = fitCy; vSpan.value = fitSpan; viewActive.value = true; }
	}
}
function onMove(ev: PointerEvent) {
	if (!cache.value) return;
	const { px, py } = localXY(ev);
	if (rectDrag && rectSel.value) {
		rectSel.value = { x: Math.min(px, startPx), y: Math.min(py, startPy), w: Math.abs(px - startPx), h: Math.abs(py - startPy) };
	} else if (panning && grab) {
		// keep the grabbed world point glued under the cursor
		const { sx, sy } = scaleFor(vSpan.value);
		const ndcX = (px / cssW) * 2 - 1, ndcY = 1 - (py / cssH) * 2;
		vCx.value = grab.x - ndcX / sx;
		vCy.value = grab.y - ndcY / sy;
		scheduleDraw();
	}
}
function onUp(ev: PointerEvent) {
	try { (ev.currentTarget as Element).releasePointerCapture(ev.pointerId); } catch { /* ignore */ }
	if (rectDrag && rectSel.value) {
		const s = rectSel.value;
		if (s.w > 6 && s.h > 6) {
			const a = screenToWorld(s.x, s.y + s.h), b = screenToWorld(s.x + s.w, s.y);
			vCx.value = (a.x + b.x) / 2; vCy.value = (a.y + b.y) / 2;
			vSpan.value = Math.max(Math.abs(b.x - a.x), Math.abs(a.y - b.y)) || vSpan.value;
			viewActive.value = true;
		}
		rectSel.value = null;
	}
	rectDrag = false; panning = false; grab = null;
	scheduleDraw();
}
</script>

<template>
	<div class="frm-cloud">
		<div v-if="loading" class="fc-msg"><v-progress-circular indeterminate small /></div>
		<div v-else-if="error" class="fc-msg err"><v-icon name="error" small /> {{ error }}</div>
		<canvas v-show="!loading && !error" ref="canvasEl"
			:class="{ rect: rectTool }"
			@wheel="onWheel" @pointerdown="onDown" @pointermove="onMove" @pointerup="onUp" @pointercancel="onUp"></canvas>

		<!-- rubber-band zoom rectangle -->
		<div v-if="rectSel" class="fc-rect" :style="{ left: rectSel.x + 'px', top: rectSel.y + 'px', width: rectSel.w + 'px', height: rectSel.h + 'px' }"></div>

		<!-- colorbar (force -> colour) -->
		<div v-if="climits && !loading && !error" class="fc-cbar">
			<span class="fc-cval">{{ fmtN(climits.cmax) }}</span>
			<div class="fc-ramp" :style="{ background: rampCss }"></div>
			<span class="fc-cval">{{ fmtN(climits.cmin) }}</span>
			<span class="fc-cunit">{{ axis }} (N)</span>
		</div>

		<!-- scale bar (mm) -->
		<div v-if="scaleBar && !loading && !error" class="fc-scale">
			<div class="fc-scale-line" :style="{ width: scaleBar.px + 'px' }"></div>
			<span>{{ scaleBar.label }}</span>
		</div>

		<!-- view tools -->
		<div v-if="!loading && !error" class="fc-tools">
			<button class="fc-tbtn" :class="{ on: rectTool }" title="Rectangular zoom (drag a box)" @click="rectTool = !rectTool">
				<v-icon name="crop_free" x-small />
			</button>
			<button class="fc-tbtn" :disabled="!zoomed" title="Reset view" @click="resetView">
				<v-icon name="restart_alt" x-small />
			</button>
		</div>

		<span v-if="!loading && !error" class="fc-count">{{ pointCount.toLocaleString() }} pts</span>
	</div>
</template>

<style scoped>
.frm-cloud { position: relative; width: 100%; height: 100%; min-height: 160px; background: #0b1020; border-radius: 6px; overflow: hidden; }
.frm-cloud canvas { width: 100%; height: 100%; display: block; cursor: grab; touch-action: none; }
.frm-cloud canvas:active { cursor: grabbing; }
.frm-cloud canvas.rect { cursor: crosshair; }
.fc-msg { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; gap: 8px; color: #94a3b8; }
.fc-msg.err { color: #fca5a5; font-size: 12px; padding: 12px; text-align: center; }
.fc-count { position: absolute; right: 6px; bottom: 4px; font-size: 10px; color: rgba(255,255,255,0.6); font-variant-numeric: tabular-nums; }

.fc-rect { position: absolute; border: 1px solid #38bdf8; background: rgba(56,189,248,0.14); pointer-events: none; border-radius: 2px; }

.fc-cbar { position: absolute; top: 10px; right: 8px; display: flex; flex-direction: column; align-items: center; gap: 3px; pointer-events: none; }
.fc-ramp { width: 10px; height: 96px; border-radius: 3px; border: 1px solid rgba(255,255,255,0.25); }
.fc-cval { font-size: 9px; color: rgba(255,255,255,0.82); font-variant-numeric: tabular-nums; }
.fc-cunit { font-size: 9px; color: rgba(255,255,255,0.6); margin-top: 1px; }

.fc-scale { position: absolute; left: 10px; bottom: 8px; display: flex; flex-direction: column; align-items: center; gap: 2px; pointer-events: none; }
.fc-scale-line { height: 3px; background: rgba(255,255,255,0.85); border-left: 1px solid rgba(255,255,255,0.85); border-right: 1px solid rgba(255,255,255,0.85); box-sizing: border-box; }
.fc-scale span { font-size: 9.5px; color: rgba(255,255,255,0.85); font-variant-numeric: tabular-nums; }

.fc-tools { position: absolute; top: 8px; left: 8px; display: flex; gap: 5px; }
.fc-tbtn { display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: 7px; cursor: pointer;
	color: rgba(255,255,255,0.85); background: rgba(15,23,42,0.55); border: 1px solid rgba(255,255,255,0.18); }
.fc-tbtn:hover { background: rgba(15,23,42,0.8); }
.fc-tbtn.on { background: #38bdf8; border-color: #38bdf8; color: #0b1020; }
.fc-tbtn:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
