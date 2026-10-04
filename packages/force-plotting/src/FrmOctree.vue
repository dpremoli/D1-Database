<script setup lang="ts">
/*
 * Full-resolution FRM viewer (Phase 2). Streams a host-built Potree octree with
 * potree-core LOD, top-down orthographic, and colours it with OUR OWN ShaderMaterial
 * that reads the Fx/Fy/Fz force attributes and applies viridis — bypassing potree-core
 * 2.0.15's broken 2.0-octree colour pipeline (its new_format shader hard-codes rgba and
 * mis-decodes it). potree-core is used purely for octree management/streaming.
 *
 * The octree carries all three axes as attributes, so switching axis is just a uniform
 * change (no reload, no shader recompile). Served same-origin by Caddy at /octrees/<path>/.
 */
import { nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { Potree, type PointCloudOctree } from 'potree-core';
import type { ColorScale } from './colorScale';
import { createScaleTexture, syncScaleTexture } from './scaleTexture';
import { exportFrmFigure } from './frmExport';
import { useForceHost } from './host';
import LoadingOverlay from './LoadingOverlay.vue';
import { createLoadToken } from './loadToken';
import { createGlLifecycle } from './glLifecycle';
import { sameStage, stageInfo, streamStage, type LoadStage, type StageInfo } from './loadStage';
import type { Cache } from './liveCache';
import { idxOfTime } from './liveCache';
import { buildPath, type PathResult } from './path';
import { findNearestPathIndex, octreePathParams, pickNearest, pointInfo, type PointMenuEvent } from './cloudPick';
import { shaderZ, timeInPath } from './octreePick';

const props = defineProps<{
	octreePath: string;                       // served subdir: /octrees/<octreePath>/
	axis: 'Fx' | 'Fy' | 'Fz';
	colorScale: ColorScale;
	pointSize: number;
	zSeries?: 'none' | 'Fx' | 'Fy' | 'Fz';    // drive the Z axis from a force series -> true 3D
	zScale?: number;                          // height exaggeration as a fraction of the x/y span
	totalPoints?: number;                     // octree's full point count -> sizes the LOD budget
	fill?: boolean;                           // grid octree: size points to tile cells into a surface
	cellSize?: number;                        // grid cell spacing (mm), for fill sizing
	minNodePx?: number;                       // Potree LOD cutoff (settings; default 1)
	budgetCap?: number;                       // Potree point-budget hard cap (settings; default 25M)
	// Linking to the Signals charts. Octree points carry no time, so a pick works by position
	// through the live cache's own path (see cloudPick.ts's header); without a cache the time
	// items are unavailable.
	sampleCache?: Cache | null;
	innerDiam?: number;                       // bore diameter (mm) the octree path was built with
	ppr?: number;                             // tacho pulses per revolution
	markTime?: number | null;                 // pinned ring (seconds on the chart axis)
	hoverTime?: number | null;                // hover ring
}>();
const emit = defineEmits<{
	(e: 'climits', v: { cmin: number; cmax: number }): void;
	(e: 'points', n: number): void;   // LOD-visible point count (for the resolution readout)
	(e: 'zscale', v: number): void;   // 3-finger vertical swipe adjusts the Z exaggeration
	(e: 'stage', v: StageInfo | null): void;   // what the view is busy with (null = idle), for the host's busy mark (#102)
	(e: 'pointmenu', v: PointMenuEvent): void;   // right-click on the map (point null = nothing resolvable)
}>();

const canvasEl = ref<HTMLCanvasElement | null>(null);
const loading = ref(true);
// 'open' while the metadata and root node load, then 'stream' while LOD nodes arrive: `loading`
// used to clear as soon as the root was in, so the rest of the full-res streaming looked finished
// (#102).
const stage = ref<LoadStage | null>({ kind: 'open' });
watch(stage, (s) => emit('stage', stageInfo(s)));
// Only the initial fill counts: after it, a pan or zoom re-streams a few nodes and a pill flashing
// on every gesture would be noise.
let lastChangeAt = performance.now();
let streamDone = false;
const error = ref<string | null>(null);
const pointCount = ref(0);

let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.OrthographicCamera | null = null;
let controls: OrbitControls | null = null;
let potree: Potree | null = null;
let pco: PointCloudOctree | null = null;
let material: THREE.ShaderMaterial | null = null;
let raf = 0;
let cssW = 1, cssH = 1;
// Render-on-demand: the RAF loop still ticks potree's LOD/streaming, but only re-renders
// when something changed (interaction, appearance, newly streamed nodes). An unconditional
// render every frame burned CPU/GPU while the view just sat there.
let needsRender = true;
let lastVisibleN = -1;
function invalidate() { needsRender = true; }
// per-axis value ranges (from the octree metadata) for auto colour limits
const ranges: Record<string, [number, number]> = { Fx: [0, 1], Fy: [0, 1], Fz: [0, 1] };
const AXIS_IDX: Record<string, number> = { Fx: 0, Fy: 1, Fz: 2 };

// One material reads all three force attributes; a uAxis uniform selects which drives
// the colour, and uRange normalises it before the viridis lookup.
function makeMaterial(): THREE.ShaderMaterial {
	const s = props.colorScale;
	const m = new THREE.ShaderMaterial({
		uniforms: {
			uGradient: { value: createScaleTexture(s) },
			uRange: { value: new THREE.Vector2(s.satMin, s.satMax) },
			// Displayed-range filter, separate from uRange (saturation/colour): a point whose raw
			// value falls outside [uDisp.x, uDisp.y] is greyed (uGreyOOR>0.5) or discarded.
			uDisp: { value: new THREE.Vector2(s.dispMin, s.dispMax) },
			uGreyOOR: { value: s.greyOutOfRange ? 1 : 0 },
			uAxis: { value: AXIS_IDX[props.axis] ?? 2 },
			uSize: { value: props.pointSize || 1.5 },
			uZAxis: { value: -1 },                        // -1 = flat (2D); 0/1/2 = Fx/Fy/Fz drive Z
			uZRange: { value: new THREE.Vector2(0, 1) },
			uZScale: { value: 0 },                        // world-unit height for the [0,1]-normalised Z
			uFill: { value: props.fill ? 1 : 0 },         // 1 = size points in world units (grid octree)
			uPxPerMm: { value: 1 },                       // updated each frame from the camera/viewport
			uCell: { value: props.cellSize || 1 },        // grid cell spacing (mm)
		},
		vertexShader: `
			attribute float Fx; attribute float Fy; attribute float Fz;
			uniform vec2 uRange; uniform float uAxis; uniform float uSize;
			uniform float uZAxis; uniform vec2 uZRange; uniform float uZScale;
			uniform float uFill; uniform float uPxPerMm; uniform float uCell;
			uniform vec2 uDisp;
			varying float vT;
			varying float vOut;   // 1 = outside the displayed range
			float pick(float i) { return i < 0.5 ? Fx : (i < 1.5 ? Fy : Fz); }
			void main() {
				float v = pick(uAxis);
				// Tested here, in the (highp) vertex stage: the mediump fragment stage can be real
				// fp16, which quantises a force edge to ~1 N and overflows OPEN_DISP to inf.
				vOut = (v < uDisp.x || v > uDisp.y) ? 1.0 : 0.0;
				vT = clamp((v - uRange.x) / max(1e-6, uRange.y - uRange.x), 0.0, 1.0);
				float z = 0.0;
				if (uZAxis >= 0.0) {
					float zv = pick(uZAxis);
					z = (clamp((zv - uZRange.x) / max(1e-6, uZRange.y - uZRange.x), 0.0, 1.0) - 0.5) * uZScale;
				}
				gl_Position = projectionMatrix * modelViewMatrix * vec4(position.xy, z, 1.0);
				gl_PointSize = uFill > 0.5 ? clamp(uCell * uPxPerMm, 1.0, 24.0) : uSize;
			}`,
		fragmentShader: `
			precision mediump float;
			uniform sampler2D uGradient; uniform float uGreyOOR;
			varying float vT; varying float vOut;
			void main() {
				vec2 d = gl_PointCoord - vec2(0.5); if (dot(d, d) > 0.25) discard;
				if (vOut > 0.5) {
					if (uGreyOOR > 0.5) { gl_FragColor = vec4(vec3(0.5), 1.0); return; }
					discard;
				}
				gl_FragColor = vec4(texture2D(uGradient, vec2(vT, 0.5)).rgb, 1.0);
			}`,
	});
	(m as any).updateMaterial = () => { /* potree calls this per frame; fixed-size = no-op */ };
	return m;
}

// The colour range currently applied (for the figure export) -- mirrors props.colorScale's own
// satMin/satMax, tracked separately only so exportViewport() need not re-derive it.
let appliedLo = 0, appliedHi = 1;
function applyRange() {
	if (!material) return;
	const s = props.colorScale;
	appliedLo = s.satMin; appliedHi = s.satMax > s.satMin ? s.satMax : s.satMin + 1;
	material.uniforms.uRange.value.set(appliedLo, appliedHi);
	material.uniforms.uDisp.value.set(s.dispMin, s.dispMax);
	material.uniforms.uGreyOOR.value = s.greyOutOfRange ? 1 : 0;
	invalidate();
}
// The octree's OWN per-axis metadata range, detected independently of whatever is currently
// applied -- lets a host reseed a fresh ColorScale (colorScale.ts's defaultScale/applyParams) on
// an axis switch, the same "climits reports the data, colorScale drives the render" split Stage 1
// established for DiagScatter.vue.
function emitAutoRange() {
	const auto = ranges[props.axis] || [0, 1];
	emit('climits', { cmin: auto[0], cmax: auto[1] });
}

// Drive the Z axis from a chosen force series -> true 3D. 'none' keeps it flat + top-down;
// otherwise the points are displaced by the (normalised) series value * uZScale, and free
// rotation is enabled so the height can be inspected.
let baseSpan = 100;
function applyZ() {
	if (!material || !controls) return;
	const z = props.zSeries || 'none';
	const idx = z === 'Fx' ? 0 : z === 'Fy' ? 1 : z === 'Fz' ? 2 : -1;
	material.uniforms.uZAxis.value = idx;
	if (idx >= 0) {
		const r = ranges[z] || [0, 1];
		material.uniforms.uZRange.value.set(r[0], r[1] > r[0] ? r[1] : r[0] + 1);
		material.uniforms.uZScale.value = baseSpan * (props.zScale ?? 0.35);
		// 3D: drag / one-finger rotates (tilt), two-finger dollies+pans. Height is inspectable.
		controls.enableRotate = true;
		controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
		controls.touches = { ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN };
	} else {
		material.uniforms.uZScale.value = 0;
		// 2D (top-down): drag / one-finger pans, two-finger dollies+pans; no rotation.
		controls.enableRotate = false;
		controls.mouseButtons = { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
		controls.touches = { ONE: THREE.TOUCH.PAN, TWO: THREE.TOUCH.DOLLY_PAN };
		frameCamera();   // snap back to a clean top-down view when flattening
	}
	ringDirty = true;
	invalidate();
}

// Returns the metadata's per-axis ranges (empty on failure -> defaults); the caller applies them
// only if its load is still current, so a superseded load can't overwrite the ranges.
async function loadMeta(base: string): Promise<Record<string, [number, number]>> {
	const found: Record<string, [number, number]> = {};
	try {
		// no-store: this metadata drives the colour limits; never risk a stale cached copy
		// (a pre-repatch metadata.json would show the wrong, un-clipped colour range).
		const res = await fetch(`${base}metadata.json`, { cache: 'no-store' });
		const meta = await res.json();
		for (const a of meta.attributes || []) {
			if (a.name in ranges && Array.isArray(a.min) && Array.isArray(a.max)) {
				found[a.name] = [Number(a.min[0]), Number(a.max[0])];
			}
		}
	} catch { /* fall back to defaults */ }
	return found;
}

// Free the current octree: its node geometries, material and gradient texture. Reloading used to
// just drop the reference (only unmount disposed), which leaked GPU memory on every op switch once
// the component stayed mounted across them.
function disposeCloud() {
	if (pco) {
		scene?.remove(pco);
		try { pco.dispose(); } catch { /* already disposed */ }
		pco = null;
	}
	(material?.uniforms.uGradient.value as THREE.Texture | undefined)?.dispose();
	material?.dispose();
	material = null;
}

// Each load() takes a token and re-checks it after every await; a superseded load disposes what
// it created and touches nothing else (two overlapping loads both reached scene.add before).
const loadToken = createLoadToken();

async function load() {
	if (life.suspended) return;   // deactivated: onActivated() reloads on a fresh canvas
	const mine = loadToken.next();
	disposeCloud();
	loading.value = true; error.value = null;
	stage.value = { kind: 'open' };
	streamDone = false;
	// The octree host is configured, not assumed to be the SPA origin: the standalone app is
	// served from a different origin than the octree server, while the Directus module is
	// same-origin. The host supplies whichever applies.
	const base = `${useForceHost().octreeUrl}/${props.octreePath}/`;
	let pt: Potree | null = null, loaded: PointCloudOctree | null = null;
	try {
		const found = await loadMeta(base);
		if (!loadToken.isCurrent(mine)) return;
		Object.assign(ranges, found);
		pt = new Potree();
		pt.maxNumNodesLoading = 12;   // parallelise node fetches so full-res streams in faster
		// "Full-res" must mean full res: budget the LOD to cover the whole octree (a small
		// headroom factor so the top level isn't shaved off), not a fixed 3M cap that left
		// large maps showing ~49%. Capped for GPU safety on the biggest maps.
		pt.pointBudget = props.totalPoints && props.totalPoints > 0
			? Math.min(Math.ceil(props.totalPoints * 1.05), props.budgetCap || 25_000_000)
			: 15_000_000;
		loaded = await pt.loadPointCloud('metadata.json', base);
		if (!loadToken.isCurrent(mine)) { loaded.dispose(); return; }
		// potree culls any octree node projecting smaller than minNodePixelSize (default
		// 50px) BEFORE the point budget is even considered — so at fit-view every deep
		// leaf is sub-50px and dropped, leaving only coarse levels (~8-50%). "Full-res"
		// must actually be full res, so drop the cutoff to ~1px; the budget above then
		// bounds the total. (Sub-pixel nodes contribute nothing visible anyway.)
		(loaded as any).minNodePixelSize = props.minNodePx || 1;
		material = makeMaterial();
		(loaded as any).material = material;
		potree = pt; pco = loaded;
		emitAutoRange();
		applyRange();
		scene!.add(pco);
		pco.updateMatrixWorld(true);
		frameCamera();
		applyZ();
		loading.value = false;
		lastChangeAt = performance.now();
		stage.value = streamStage(0, props.totalPoints, 0);
	} catch (e: any) {
		if (!loadToken.isCurrent(mine)) { try { loaded?.dispose(); } catch { /* ignore */ } return; }
		error.value = e?.message || 'failed to load octree';
		loading.value = false;
		stage.value = null;
	}
}

function frameCamera() {
	if (!pco || !camera || !controls) return;
	const box = pco.boundingBox.clone().applyMatrix4(pco.matrixWorld);
	const c = box.getCenter(new THREE.Vector3()), sz = box.getSize(new THREE.Vector3());
	baseSpan = Math.max(sz.x, sz.y) || 100;
	const span = baseSpan * 1.08, aspect = cssW / cssH;
	camera.left = -span / 2 * aspect; camera.right = span / 2 * aspect; camera.top = span / 2; camera.bottom = -span / 2;
	camera.position.set(c.x, c.y, c.z + 1e5); camera.up.set(0, 1, 0); camera.lookAt(c.x, c.y, c.z);
	camera.updateProjectionMatrix();
	controls.target.set(c.x, c.y, c.z); controls.update();
	invalidate();
}

function setupGL() {
	const canvas = canvasEl.value!;
	sizeCanvas();
	try {
		renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true });
	} catch { error.value = 'WebGL unavailable'; return; }
	renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
	renderer.setClearColor(0x000000, 0);
	scene = new THREE.Scene();
	camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 1e7);
	controls = new OrbitControls(camera, canvas);
	controls.enableRotate = false;
	controls.mouseButtons = { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
	controls.touches = { ONE: THREE.TOUCH.PAN, TWO: THREE.TOUCH.DOLLY_PAN };
	canvas.addEventListener('pointerdown', onPtrDown);
	canvas.addEventListener('pointermove', onPtrMove);
	canvas.addEventListener('pointerup', onPtrUp);
	canvas.addEventListener('pointercancel', onPtrUp);
	canvas.addEventListener('contextmenu', onContextMenu);
	controls.addEventListener('change', invalidate);
	const loop = () => {
		raf = requestAnimationFrame(loop);
		controls!.update();
		if (pco && potree && renderer && camera) {
			updateRings();   // before the render gate below: the rings follow the camera even on idle frames
			const r = potree.updatePointClouds([pco], camera, renderer);
			const n = (r as any)?.numVisiblePoints ?? pointCount.value;
			if (n !== lastVisibleN) { lastVisibleN = n; needsRender = true; lastChangeAt = performance.now(); }   // nodes streamed in/out
			if (!loading.value && !streamDone) {
				const next = streamStage(n, props.totalPoints, performance.now() - lastChangeAt);
				if (!next) streamDone = true;
				if (!sameStage(stage.value, next)) stage.value = next;
			}
			if (Math.abs(n - pointCount.value) > pointCount.value * 0.02 + 1) { pointCount.value = n; emit('points', n); }
			if (!needsRender) return;
			needsRender = false;
			if (material && props.fill) {
				// orthographic: world width shown = (right-left)/zoom; px width = domElement.width.
				const worldW = (camera.right - camera.left) / (camera.zoom || 1);
				material.uniforms.uPxPerMm.value = worldW > 0 ? (renderer.domElement.width / worldW) : 1;
			}
			renderer.render(scene!, camera);
		}
	};
	loop();
}

// 3-finger vertical swipe adjusts the Z exaggeration (only when a Z series is loaded). Swiping
// up spreads the points apart in Z; down flattens. Tracked via POINTER events (not touch) so it
// coexists with OrbitControls' pointer capture — touch events can be suppressed once a pointer is
// captured, which is why a touch-based handler didn't fire. OrbitControls is paused for the
// gesture; the new value is emitted and the parent owns zScale, feeding it back.
const zPointers = new Map<number, number>();   // pointerId -> clientY
let zBaseY = 0;
function avgVals(m: Map<number, number>): number { let s = 0; for (const v of m.values()) s += v; return s / (m.size || 1); }
function onPtrDown(ev: PointerEvent) {
	// OrbitControls pans on right-drag (2D and 3D), and the browser still fires `contextmenu` on
	// release, so remember where the button went down to tell a click from a pan.
	if (ev.pointerType === 'mouse' && ev.button === 2) { rightDownX = ev.clientX; rightDownY = ev.clientY; }
	if (ev.pointerType !== 'touch') return;
	zPointers.set(ev.pointerId, ev.clientY);
	if (zPointers.size === 3) { if (controls) controls.enabled = false; zBaseY = avgVals(zPointers); }
}
function onPtrMove(ev: PointerEvent) {
	if (!zPointers.has(ev.pointerId)) return;
	zPointers.set(ev.pointerId, ev.clientY);
	if (zPointers.size >= 3 && props.zSeries && props.zSeries !== 'none') {
		const y = avgVals(zPointers);
		const dy = zBaseY - y;   // swipe up (dy > 0) => more Z separation
		zBaseY = y;
		const cur = Math.max(0.02, props.zScale ?? 0.35);
		emit('zscale', Number(Math.min(3, Math.max(0, cur * Math.exp(dy * 0.006))).toFixed(4)));
	}
}
function onPtrUp(ev: PointerEvent) {
	zPointers.delete(ev.pointerId);
	if (zPointers.size < 3 && controls) controls.enabled = true;
}

// ---- Linking to the Signals charts: right-click picking and time rings ----
// The octree has no per-point time, so both directions go through the live cache's own path
// (octreePathParams + buildPath: the same mm frame and geometry the octree was built with; see
// cloudPick.ts's header). Path positions are true world mm (potree-core restores the LAS
// offset), so no pco matrix is applied to them.
let rightDownX = NaN, rightDownY = NaN;
let memoCache: Cache | null = null, memoInner = NaN, memoPpr = NaN;
let memoPath: PathResult | null = null;
// Memoised per (cache identity, innerDiam, ppr): a rebuild walks the whole cache (up to ~5M samples).
function samplePath(): PathResult | null {
	const c = props.sampleCache;
	if (!c) { memoCache = null; memoPath = null; return null; }
	const inner = props.innerDiam ?? 0, ppr = props.ppr ?? 1;
	if (c !== memoCache || inner !== memoInner || ppr !== memoPpr) {
		const { path, window } = octreePathParams(c, inner, ppr);
		memoPath = buildPath(c, path, window);
		memoCache = c; memoInner = inner; memoPpr = ppr;
	}
	return memoPath;
}

const _v = new THREE.Vector3();
// World position of path sample k into _v, with Z matching the vertex shader (flat = 0).
function sampleWorld(path: PathResult, k: number): THREE.Vector3 {
	const c = props.sampleCache!;
	let z = 0;
	const zAxis = material ? (material.uniforms.uZAxis.value as number) : -1;
	if (material && zAxis >= 0) {
		const r = material.uniforms.uZRange.value as THREE.Vector2;
		const series = zAxis === 0 ? c.Fx : zAxis === 1 ? c.Fy : c.Fz;
		z = shaderZ(series[path.idx[k]], r.x, r.y, material.uniforms.uZScale.value as number);
	}
	return _v.set(path.pos[3 * k], path.pos[3 * k + 1], z);
}
// CSS px relative to the canvas; false when the point is outside the view (clip) unless `clip` is off.
function toScreen(v: THREE.Vector3, out: { px: number; py: number }, clip = true): boolean {
	v.project(camera!);
	if (clip && (v.x < -1 || v.x > 1 || v.y < -1 || v.y > 1)) return false;
	out.px = (v.x + 1) / 2 * cssW; out.py = (1 - v.y) / 2 * cssH;
	return true;
}

function onContextMenu(ev: MouseEvent) {
	ev.preventDefault();
	const moved = Math.hypot(ev.clientX - rightDownX, ev.clientY - rightDownY) > 4;
	rightDownX = rightDownY = NaN;
	if (moved || !canvasEl.value || !camera) return;
	const base = { clientX: ev.clientX, clientY: ev.clientY };
	const c = props.sampleCache;
	const path = samplePath();
	if (!c || !path) { emit('pointmenu', { ...base, point: null, reason: 'no-cache' }); return; }
	const r = canvasEl.value.getBoundingClientRect();
	const px = ev.clientX - r.left, py = ev.clientY - r.top;
	camera.updateMatrixWorld();   // controls.update() moved it since the last render
	const pp = { px: 0, py: 0 };
	// Mirrors the shader's displayed-range discard (a greyed point is still drawn, so still pickable).
	const s = props.colorScale;
	const vals = c[props.axis];
	const keep = s.greyOutOfRange ? undefined : (k: number) => { const v = vals[path.idx[k]]; return v >= s.dispMin && v <= s.dispMax; };
	// Gridded octrees (`fill`) still pick the nearest SAMPLE to the spot: cells aren't samples.
	const k = pickNearest(path.count, (i) => (toScreen(sampleWorld(path, i), pp) ? pp : null),
		px, py, Math.max(8, (props.pointSize || 1.5) * 2), keep);
	if (k === null) { emit('pointmenu', { ...base, point: null }); return; }
	emit('pointmenu', { ...base, point: pointInfo(c, path.idx[k], path.pos[3 * k], path.pos[3 * k + 1], path.rho?.[k]) });
}

// Ring overlays (CSS px in the canvas box). Positions are refs so the template moves them; they
// are only written when a ring actually moved >= 0.25 px, so idle frames cost no reactivity.
const markRing = ref<{ x: number; y: number } | null>(null);
const hoverRing = ref<{ x: number; y: number } | null>(null);
const _pt = { px: 0, py: 0 };
// The path position k of the sample nearest time `sec`, or -1 (no cache, or outside the path's span).
function pathIndexAt(sec: number | null | undefined): number {
	const c = props.sampleCache, path = samplePath();
	if (sec == null || !c || !path || !timeInPath(c.t, path.idx, path.count, sec)) return -1;
	return findNearestPathIndex(path.idx, path.count, idxOfTime(c.t, sec));
}
function ringPos(sec: number | null | undefined): { x: number; y: number } | null {
	const k = pathIndexAt(sec);
	if (k < 0) return null;
	return toScreen(sampleWorld(samplePath()!, k), _pt) ? { x: _pt.px, y: _pt.py } : null;
}
function setRing(r: typeof markRing, v: { x: number; y: number } | null) {
	const o = r.value;
	if (!v || !o) { if (o !== v) r.value = v; return; }
	if (Math.abs(o.x - v.x) >= 0.25 || Math.abs(o.y - v.y) >= 0.25) r.value = v;
}
// What the ring positions depend on, compared in place each frame (no allocation): camera
// framing, canvas size, the shader's Z mapping and the two times. `ringDirty` covers what
// can't be a number (cache identity, innerDiam, ppr, octree reload).
const ringSig = new Float64Array(20).fill(NaN);
const _sig = new Float64Array(20);
let ringDirty = true;
function updateRings() {
	if (!camera || !controls) return;
	const u = material?.uniforms;
	const zr = u?.uZRange.value as THREE.Vector2 | undefined;
	const p = camera.position, t = controls.target, q = camera.quaternion;
	_sig[0] = camera.zoom; _sig[1] = p.x; _sig[2] = p.y; _sig[3] = p.z;
	_sig[4] = t.x; _sig[5] = t.y; _sig[6] = t.z;
	_sig[7] = q.x; _sig[8] = q.y; _sig[9] = q.z; _sig[10] = q.w;
	_sig[11] = camera.left; _sig[12] = camera.right; _sig[13] = camera.top; _sig[14] = camera.bottom;
	_sig[15] = cssW; _sig[16] = cssH;
	_sig[17] = u ? u.uZAxis.value * 1e6 + u.uZScale.value : 0;
	_sig[18] = zr ? zr.x + zr.y : 0;
	let changed = ringDirty;
	for (let i = 0; i < _sig.length && !changed; i++) if (_sig[i] !== ringSig[i]) changed = true;
	if (!changed) return;
	ringSig.set(_sig); ringDirty = false;
	if (!props.sampleCache) { setRing(markRing, null); setRing(hoverRing, null); return; }
	camera.updateMatrixWorld();
	setRing(markRing, ringPos(props.markTime));
	setRing(hoverRing, ringPos(props.hoverTime));
}
watch(() => [props.sampleCache, props.innerDiam, props.ppr, props.markTime, props.hoverTime], () => { ringDirty = true; });

// Bring the sample at time t into view (pans the target and camera together so the view angle
// is unchanged). false when there is no sample for t (no cache, or outside the cut window).
function revealTime(t: number): boolean {
	if (!camera || !controls) return false;
	const k = pathIndexAt(t);
	if (k < 0) return false;
	camera.updateMatrixWorld();
	const v = sampleWorld(samplePath()!, k);
	const flat = !material || (material.uniforms.uZAxis.value as number) < 0;
	const d = v.clone().sub(controls.target);   // a rare call: allocation is fine here
	if (flat) d.z = 0;
	if (toScreen(v.clone(), _pt)) return true;   // already in view
	controls.target.add(d); camera.position.add(d);
	controls.update(); invalidate(); ringDirty = true;
	return true;
}

function sizeCanvas() {
	const canvas = canvasEl.value; if (!canvas) return;
	const r = canvas.getBoundingClientRect();
	cssW = Math.max(1, r.width); cssH = Math.max(1, r.height);
	renderer?.setSize(cssW, cssH, false);
}

let ro: ResizeObserver | undefined;
// Bumped on reactivation: teardown force-loses the GL context and a canvas never gets a lost
// context back, so the template swaps in a new element (see glLifecycle.ts).
const canvasKey = ref(0);
function boot() {
	setupGL();
	if (canvasEl.value) ro?.observe(canvasEl.value);
	load();
}
// Stops the rAF/Potree loop, frees the octree's GPU memory and the GL context, and makes any load
// still in flight stale. Runs on unmount AND on deactivate: this viewer lives inside the kept-alive
// Plot route (#24/#57), so without the deactivate half it kept streaming (up to ~25M points of GPU
// memory) while the operator was on the Record page (review 3.6).
function teardownGL() {
	loadToken.cancel();
	// The stage watcher is already stopped on unmount: say "idle" directly so the host's busy bar clears.
	if (stage.value) emit('stage', null);
	stage.value = null;
	if (raf) cancelAnimationFrame(raf);
	raf = 0;
	const c = canvasEl.value;
	if (c) {
		c.removeEventListener('pointerdown', onPtrDown);
		c.removeEventListener('pointermove', onPtrMove);
		c.removeEventListener('pointerup', onPtrUp);
		c.removeEventListener('pointercancel', onPtrUp);
		c.removeEventListener('contextmenu', onContextMenu);
	}
	zPointers.clear();
	ro?.disconnect(); controls?.dispose();
	disposeCloud();
	try { renderer?.forceContextLoss(); } catch { /* ignore */ }   // release the GL context (not freed by dispose())
	renderer?.dispose();
	renderer = null; scene = null; camera = null; controls = null; potree = null;
	loading.value = true;
}
const life = createGlLifecycle({
	teardown: teardownGL,
	replaceCanvas: () => { canvasKey.value++; error.value = null; },
	start: () => nextTick(boot),
});
onMounted(() => {
	ro = new ResizeObserver(() => { sizeCanvas(); frameCamera(); });
	nextTick(boot);
});
onBeforeUnmount(() => life.unmount());
onDeactivated(() => life.deactivate());
onActivated(() => { life.activate(); });

watch(() => props.octreePath, () => { load(); });
watch(() => props.axis, () => { if (material) { material.uniforms.uAxis.value = AXIS_IDX[props.axis] ?? 2; emitAutoRange(); } });
// LUT bytes resync only when lutKey changes; saturation/displayed-range/grey-vs-hide are uniforms.
watch(() => props.colorScale, (s) => {
	if (!material) return;
	syncScaleTexture(material.uniforms.uGradient.value, s);
	applyRange();
}, { deep: true });
watch(() => props.pointSize, () => { if (material) { material.uniforms.uSize.value = props.pointSize || 1.5; invalidate(); } });
watch(() => [props.fill, props.cellSize], () => {
	if (material) {
		material.uniforms.uFill.value = props.fill ? 1 : 0;
		material.uniforms.uCell.value = props.cellSize || 1;
		invalidate();
	}
});
watch(() => [props.zSeries, props.zScale], applyZ);

// The world rectangle (mm) the orthographic camera currently shows (pan target ± half the
// zoom-scaled frustum). Meaningful in the flat 2D view; the export is a 2D figure anyway.
function currentBounds(): { xmin: number; xmax: number; ymin: number; ymax: number } {
	if (!camera) return { xmin: -1, xmax: 1, ymin: -1, ymax: 1 };
	const cx = controls?.target.x ?? camera.position.x;
	const cy = controls?.target.y ?? camera.position.y;
	const hw = (camera.right - camera.left) / 2 / (camera.zoom || 1);
	const hh = (camera.top - camera.bottom) / 2 / (camera.zoom || 1);
	return { xmin: cx - hw, xmax: cx + hw, ymin: cy - hh, ymax: cy + hh };
}
// Export the current view as a formatted FRM figure (client-side, no host round-trip). The
// render loop paints every frame + preserveDrawingBuffer is on, so the canvas pixels are live.
function exportViewport(filename: string, subtitle?: string) {
	const c = canvasEl.value;
	if (!c) return false;
	return exportFrmFigure({
		canvas: c, bounds: currentBounds(),
		cmin: appliedLo, cmax: appliedHi, colorScale: props.colorScale,
		axis: props.axis, subtitle, filename,
	});
}
defineExpose({ currentBounds, exportViewport, revealTime });
</script>

<template>
	<div class="frm-octree">
		<LoadingOverlay v-if="stage" :stage="stage" />
		<div v-if="error" class="fc-msg err"><v-icon name="error" small /> {{ error }}</div>
		<canvas :key="canvasKey" v-show="!error" ref="canvasEl"></canvas>
		<span v-if="markRing" class="fo-ring mark" :style="{ transform: `translate(${markRing.x}px, ${markRing.y}px)` }"></span>
		<span v-if="hoverRing" class="fo-ring hover" :style="{ transform: `translate(${hoverRing.x}px, ${hoverRing.y}px)` }"></span>
		<span v-if="!loading && !error" class="fc-count">{{ pointCount.toLocaleString() }} pts (LOD)</span>
	</div>
</template>

<style scoped>
.frm-octree { position: relative; width: 100%; height: 100%; min-height: 160px; background: var(--plot-bg, #0b1020); border-radius: 6px; overflow: hidden; }
.frm-octree canvas { width: 100%; height: 100%; display: block; cursor: grab; touch-action: none; }
.frm-octree canvas:active { cursor: grabbing; }
/* Rings sit centred on their point: the box is offset by half its size from the translate origin. */
.fo-ring { position: absolute; left: 0; top: 0; pointer-events: none; border-radius: 50%; box-sizing: border-box; }
.fo-ring.mark { width: 12px; height: 12px; margin: -6px 0 0 -6px; border: 2px solid var(--accent, #38bdf8); background: color-mix(in srgb, var(--accent, #38bdf8) 35%, transparent); }
.fo-ring.hover { width: 10px; height: 10px; margin: -5px 0 0 -5px; border: 1.5px solid var(--accent, #38bdf8); opacity: 0.7; }
.fc-msg { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; gap: 8px; color: var(--text-dim, #94a3b8); }
.fc-msg.err { color: var(--danger, #fca5a5); font-size: var(--fs-sm, 12px); padding: 12px; text-align: center; }
.fc-count { position: absolute; right: 6px; bottom: 4px; font-size: var(--fs-xs, 11px); color: var(--text-dim, rgba(255,255,255,0.6)); font-variant-numeric: tabular-nums; }
</style>
