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
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { type Cache, cacheGet, cachePut, parseCache } from './liveCache';
import { type Axis, type Cloud, type SpeedMode, buildCloud, COLORMAPS } from './liveCloud';
import { exportFrmFigure } from './frmExport';

const props = defineProps<{
	cacheFileId: string;
	axis: Axis;
	feed: number;
	diam: number;
	innerDiam: number;
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
	zSeries?: 'none' | 'Fx' | 'Fy' | 'Fz';    // drive Z from a force series -> true 3D (like Full)
	zScale?: number;                          // height exaggeration as a fraction of the x/y span
}>();
const emit = defineEmits<{
	(e: 'loaded', meta: { csSec: number; ceSec: number; feed: number; diam: number; rpm: number; Fs: number; N: number }): void;
	(e: 'climits', v: { cmin: number; cmax: number }): void;
	(e: 'points', n: number): void;   // rendered point count (for the resolution readout)
	(e: 'zscale', v: number): void;   // 3-finger vertical swipe adjusts the Z exaggeration
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
// NOT immediate: an immediate watch runs during setup(), and on the precached (cache
// already in the LRU) path load() runs *synchronously* there — before the view-state
// refs below (viewActive, vCx…) are initialised — throwing "Cannot access 'viewActive'
// before initialization". The initial load is kicked off from onMounted instead (after
// setup completes, so every ref exists); this watch only handles later cacheFileId
// changes (switching ops while mounted), which already run post-setup.
watch(() => props.cacheFileId, (id) => { if (id) load(id); });

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
let pointsObj: THREE.Points | null = null;
let discTex: THREE.CanvasTexture | null = null;
let controls: OrbitControls | null = null;   // 3D mode only (Z series active)
let ready = false;
// 3D when a Z series is selected: the cloud gets a Z displacement and OrbitControls owns
// the camera; the custom 2D pan/pinch/wheel/rect handlers stand down. Flat is unchanged.
const is3D = computed(() => !!props.zSeries && props.zSeries !== 'none');

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
	camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 1e6);   // far covers 3D orbit distances
	camera.position.set(0, 0, 10);
	discTex = makeDisc();
	pointsGeom = new THREE.BufferGeometry();
	pointsMat = new THREE.PointsMaterial({ size: 1.4, sizeAttenuation: false, vertexColors: true, map: discTex, alphaTest: 0.5, transparent: false });
	pointsObj = new THREE.Points(pointsGeom, pointsMat);
	scene.add(pointsObj);
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
		axis: props.axis, feed: props.feed, diam: props.diam, innerDiam: props.innerDiam,
		speedMode: props.speedMode, rpm: props.rpm, vc: props.vc, timeScale: props.timeScale, ppr: props.ppr,
		cropStartSec: props.cropStartSec, cropEndSec: props.cropEndSec,
		stride: props.stride, gridding: props.gridding, gridN: props.gridN,
		colormap: COLORMAPS[props.colormap] || COLORMAPS.viridis,
		cmin: props.cmin, cmax: props.cmax,
		zSeries: props.zSeries || 'none',
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
	// Z displacement: stored centred (-0.5..0.5); the Points object's scale.z turns it into
	// world units, so exaggeration changes (slider / 3-finger swipe) cost no rebuild.
	if (cloud.zv) for (let k = 0; k < n; k++) pos3[k * 3 + 2] = cloud.zv[k];
	pointsGeom.setAttribute('position', new THREE.BufferAttribute(pos3, 3));
	pointsGeom.setAttribute('color', new THREE.BufferAttribute(cloud.col, 3));
	pointsGeom.setDrawRange(0, n);
	applyZScale();
	if (is3D.value && !controls) enter3D();   // mounted straight into 3D (Z picked before Lite)

	// colorbar limits (only changes with the cloud)
	const cl = { cmin: cloud.cmin, cmax: cloud.cmax };
	if (!climits.value || climits.value.cmin !== cl.cmin || climits.value.cmax !== cl.cmax) {
		climits.value = cl; emit('climits', cl);
	}
}

// Z exaggeration in world units = fraction of the data span; applied via the Points
// object's scale.z over the centred (-0.5..0.5) Z attribute (free — no rebuild).
function applyZScale() {
	if (!pointsObj) return;
	pointsObj.scale.z = is3D.value ? Math.max(0.001, fitSpan * (props.zScale ?? 0.35)) : 1;
}

// Enter 3D: OrbitControls takes the camera (rotate/dolly/pan) framed on the cloud.
// Exit: reset the camera pose so the 2D per-draw frustum math is authoritative again.
function enter3D() {
	if (!canvasEl.value || !camera) return;
	if (!controls) {
		controls = new OrbitControls(camera, canvasEl.value);
		controls.addEventListener('change', scheduleDraw);
		controls.touches = { ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN };
		controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
		controls.enableDamping = false;
	}
	controls.enabled = true;
	// frame: top-down on the data centre; frustum sized to the fit span
	const aspect = cssW / cssH || 1;
	const half = (fitSpan * 1.1) / 2;
	camera.left = -half * (aspect >= 1 ? aspect : 1); camera.right = -camera.left;
	camera.top = half / (aspect >= 1 ? 1 : aspect); camera.bottom = -camera.top;
	camera.zoom = 1;
	camera.position.set(fitCx, fitCy, fitSpan * 2);
	camera.up.set(0, 1, 0);
	camera.lookAt(fitCx, fitCy, 0);
	camera.updateProjectionMatrix();
	controls.target.set(fitCx, fitCy, 0);
	controls.update();
}
function exit3D() {
	if (controls) controls.enabled = false;
	if (camera) { camera.rotation.set(0, 0, 0); camera.up.set(0, 1, 0); camera.zoom = 1; }
}
watch(is3D, (on) => {
	if (on) enter3D(); else exit3D();
	applyZScale();
	scheduleDraw();
});
watch(() => props.zScale, () => { applyZScale(); scheduleDraw(); });

// View-only redraw: no recompute, no re-upload — just drive the orthographic camera
// from the current view and render the resident geometry. Cheap enough per frame.
function draw() {
	if (!ready || !renderer || !scene || !camera || !canvasEl.value || !cloud) return;
	sizeCanvas(canvasEl.value);
	if (is3D.value) {
		// OrbitControls owns the camera; just render.
		if (pointsMat) pointsMat.size = Math.max(1, props.pointSize || 1.4);
		renderer.render(scene, camera);
		scaleBar.value = null;   // a rotated view has no single mm-per-px
		return;
	}
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
// Export the CURRENT viewport (whatever zoom/pan the user is looking at) as a formatted FRM
// figure — instant, client-side, no host round-trip. Forces a fresh draw first (the renderer
// keeps preserveDrawingBuffer) and composites the report styling (axes/colorbar/title) around it.
function exportViewport(filename: string, subtitle?: string) {
	if (is3D.value) return false;   // a rotated 3D view has no meaningful 2D axes -> fall back
	const c = canvasEl.value;
	if (!c || !ready) return false;
	draw();
	const cl = climits.value;
	return exportFrmFigure({
		canvas: c, bounds: currentBounds(),
		cmin: cl?.cmin ?? 0, cmax: cl?.cmax ?? 1,
		colormap: props.colormap, axis: props.axis, subtitle, filename,
	});
}
defineExpose({ currentBounds, exportViewport });

let ro: ResizeObserver | undefined;
onMounted(() => {
	ro = new ResizeObserver(() => scheduleDraw());
	// Kick off the initial cache load here (post-setup) rather than via an immediate
	// watch, so the synchronous precached path can't touch not-yet-initialised refs.
	if (props.cacheFileId) load(props.cacheFileId);
	else if (cache.value) nextTick(() => { setupRenderer(); scheduleRebuild(); });
});
onBeforeUnmount(() => {
	if (raf) cancelAnimationFrame(raf);
	ro?.disconnect();
	if (cropTimer) clearTimeout(cropTimer);
	controls?.dispose();
	pointsGeom?.dispose(); pointsMat?.dispose(); discTex?.dispose(); renderer?.dispose();
});

// Geometry/colour props → rebuild immediately. pointSize is view-only (a uniform).
watch(() => [props.axis, props.feed, props.diam, props.innerDiam, props.speedMode, props.rpm, props.vc, props.timeScale, props.ppr,
	props.stride, props.gridding, props.gridN, props.colormap, props.cmin, props.cmax, props.zSeries], scheduleRebuild);
watch(() => props.pointSize, scheduleDraw);

// Crop is DRAGGED, and its rebuild is the full O(N) recompute + percentile sort + GPU
// re-upload — running that every drag frame is what makes millions-of-points laggy. So
// throttle it to ~12fps (leading rebuild, then a trailing one so the final crop is
// exact). The force charts' crop shading stays instant regardless (cheap SVG overlay).
let cropTimer = 0, cropTrailing = false;
function onCropChange() {
	if (cropTimer) { cropTrailing = true; return; }
	scheduleRebuild();
	const step = () => {
		cropTimer = 0;
		if (cropTrailing) { cropTrailing = false; scheduleRebuild(); cropTimer = window.setTimeout(step, 80); }
	};
	cropTimer = window.setTimeout(step, 80);
}
watch(() => [props.cropStartSec, props.cropEndSec], onCropChange);

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
	if (is3D.value) return;   // OrbitControls owns wheel-zoom in 3D
	ev.preventDefault();
	const { px, py } = localXY(ev);
	const w = screenToWorld(px, py);
	// Magnitude-aware zoom. The old code stepped a fixed 1.2x per wheel EVENT (sign only),
	// so a free-spinning / high-res wheel — which emits a burst of events per physical
	// notch — multiplied that dozens of times and slammed straight to max zoom. Normalise
	// the delta across device units (px / lines / pages), clamp a single event's reach,
	// and scale continuously so one notch ≈ 1.2x regardless of how it's delivered.
	let dy = ev.deltaY;
	if (ev.deltaMode === 1) dy *= 16;                       // lines -> ~px
	else if (ev.deltaMode === 2) dy *= (cssH || 600);       // pages -> ~px
	dy = Math.max(-100, Math.min(100, dy));                 // cap one event to ~one notch
	const f = Math.exp(-dy * 0.00182);                      // ~1.2x per 100px notch
	const v = effView();
	const newSpan = Math.min(fitSpan * 8, Math.max(fitSpan / 500, v.span / f));
	const { sx, sy } = scaleFor(newSpan);
	vCx.value = w.x - w.ndcX / sx;
	vCy.value = w.y - w.ndcY / sy;
	vSpan.value = newSpan;
	viewActive.value = true;
	scheduleDraw();
}
// Active pointers, so touch can pinch-zoom (two fingers) as well as pan (one). Desktop
// still uses the wheel; mobile had NO zoom before this — a single pointer only panned.
const pointers = new Map<number, { px: number; py: number }>();
let pinch: { dist: number; span: number; cx: number; cy: number } | null = null;
function pointerList() { return [...pointers.values()]; }
function pointerDist() { const p = pointerList(); return Math.hypot(p[0].px - p[1].px, p[0].py - p[1].py); }
function pointerMid() { const p = pointerList(); return { px: (p[0].px + p[1].px) / 2, py: (p[0].py + p[1].py) / 2 }; }
function seedView() { if (!viewActive.value) { vCx.value = fitCx; vCy.value = fitCy; vSpan.value = fitSpan; viewActive.value = true; } }

// 3-finger vertical drag adjusts the Z exaggeration in 3D (same gesture as Full).
let zGestureY: number | null = null;
function avgPy(): number { let s = 0; for (const p of pointers.values()) s += p.py; return s / (pointers.size || 1); }

function onDown(ev: PointerEvent) {
	if (!cache.value) return;
	const { px, py } = localXY(ev);
	(ev.currentTarget as Element).setPointerCapture(ev.pointerId);
	pointers.set(ev.pointerId, { px, py });
	if (is3D.value) {
		// OrbitControls handles 1/2-finger via its own listeners; we only run the 3-finger gesture
		if (pointers.size === 3 && controls) { controls.enabled = false; zGestureY = avgPy(); }
		return;
	}
	if (pointers.size === 2) {
		// second finger down -> start a pinch; abandon any pan/rect in progress
		panning = false; rectDrag = false; rectSel.value = null;
		seedView();
		const mid = pointerMid(); const w = screenToWorld(mid.px, mid.py);
		pinch = { dist: pointerDist() || 1, span: vSpan.value, cx: w.x, cy: w.y };
		return;
	}
	if (pointers.size > 2) return;
	if (rectTool.value) {
		rectDrag = true; startPx = px; startPy = py; rectSel.value = { x: px, y: py, w: 0, h: 0 };
	} else {
		panning = true; grab = { x: screenToWorld(px, py).x, y: screenToWorld(px, py).y };
		seedView();
	}
}
function onMove(ev: PointerEvent) {
	if (!cache.value) return;
	const { px, py } = localXY(ev);
	if (pointers.has(ev.pointerId)) pointers.set(ev.pointerId, { px, py });
	if (is3D.value) {
		if (zGestureY != null && pointers.size >= 3 ) {
			const y = avgPy(); const dy = zGestureY - y; zGestureY = y;   // up = more separation
			const cur = Math.max(0.02, props.zScale ?? 0.35);
			emit('zscale', Number(Math.min(3, Math.max(0, cur * Math.exp(dy * 0.006))).toFixed(4)));
		}
		return;
	}
	if (pinch && pointers.size >= 2) {
		// pinch-zoom: keep the world point under the finger midpoint fixed (spread = zoom in)
		const d = pointerDist();
		if (d > 0) {
			const newSpan = Math.min(fitSpan * 8, Math.max(fitSpan / 500, pinch.span * (pinch.dist / d)));
			const mid = pointerMid();
			const { sx, sy } = scaleFor(newSpan);
			const ndcX = (mid.px / cssW) * 2 - 1, ndcY = 1 - (mid.py / cssH) * 2;
			vSpan.value = newSpan; vCx.value = pinch.cx - ndcX / sx; vCy.value = pinch.cy - ndcY / sy;
			scheduleDraw();
		}
		return;
	}
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
	pointers.delete(ev.pointerId);
	if (is3D.value) {
		if (pointers.size < 3) { zGestureY = null; if (controls) controls.enabled = true; }
		return;
	}
	if (pointers.size < 2) pinch = null;
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
