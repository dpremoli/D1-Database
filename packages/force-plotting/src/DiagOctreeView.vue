<script setup lang="ts">
/*
 * Diagnostics octree viewer. Streams a host-built Potree octree with potree-core LOD, top-down
 * orthographic, and colours it with OUR OWN ShaderMaterial that reads the diag attributes
 * (tsa_resid, resid_z) and applies viridis — bypassing potree-core 2.0.15's broken 2.0-octree
 * colour pipeline, same as FrmOctree.vue. potree-core is used purely for octree management/
 * streaming. Only analyse()'s own columns are ever registered as LAS extra dims by
 * process_diag_row (see scripts/force_orchestrator.py) — Fx/Fy/Fz are deliberately NOT among
 * the channel options here, unlike FrmOctree.vue's raw-cloud octrees which do carry them.
 *
 * This is FrmOctree.vue's pattern generalized two ways: the axis uniform becomes a wider
 * "channel" uniform covering the diag attributes too, and a selection-highlight uniform dims
 * points outside the active cross-panel selection (time / attribute-threshold; spatial lasso's
 * shader side is deferred — see selection.ts). Z-height and grid-fill are FrmOctree-specific
 * features not needed here and are not carried over.
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { Potree, type PointCloudOctree } from 'potree-core';
import { COLORMAPS } from './liveCloud';
import { exportFrmFigure } from './frmExport';
import { useForceHost } from './host';
import type { Selection } from './selection';

const props = defineProps<{
	octreePath: string;                       // served subdir: /octrees/diag/<octreePath>/
	channel: 'tsaResid' | 'residZ';
	colormap: string;
	pointSize: number;
	cmin?: number | null;
	cmax?: number | null;
	totalPoints?: number;                     // octree's full point count -> sizes the LOD budget
	minNodePx?: number;                       // Potree LOD cutoff (settings; default 1)
	budgetCap?: number;                       // Potree point-budget hard cap (settings; default 25M)
	selection?: Selection;
}>();
const emit = defineEmits<{
	(e: 'climits', v: { cmin: number; cmax: number }): void;
	(e: 'points', n: number): void;   // LOD-visible point count (for the resolution readout)
}>();

const canvasEl = ref<HTMLCanvasElement | null>(null);
const loading = ref(true);
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
// per-channel value ranges (from the octree metadata) for auto colour limits. Keyed by the
// prop's camelCase channel names; ATTR_NAME maps each to the octree's actual (snake_case) LAS
// extra-dim attribute name for matching against metadata.json's `attributes[].name`.
const ranges: Record<string, [number, number]> = { tsaResid: [0, 1], residZ: [0, 1] };
const ATTR_NAME: Record<string, string> = { tsaResid: 'tsa_resid', residZ: 'resid_z' };
const CHANNEL_IDX: Record<string, number> = { tsaResid: 0, residZ: 1 };
const SEL_KIND_IDX: Record<string, number> = { time: 1, attribute: 2, lasso: 3 };

function gradientTexture(name: string): THREE.DataTexture {
	const cm = COLORMAPS[name] || COLORMAPS.viridis;
	const N = 256, data = new Uint8Array(N * 4);
	for (let i = 0; i < N; i++) {
		const [r, g, b] = cm(i / (N - 1));
		data[i * 4] = r * 255; data[i * 4 + 1] = g * 255; data[i * 4 + 2] = b * 255; data[i * 4 + 3] = 255;
	}
	const t = new THREE.DataTexture(data, N, 1, THREE.RGBAFormat);
	t.minFilter = THREE.LinearFilter; t.magFilter = THREE.LinearFilter; t.needsUpdate = true;
	return t;
}

// One material reads tsa_resid/resid_z; a uChannel uniform selects which drives the colour, and
// uRange normalises it before the viridis lookup. A separate selection-highlight
// path (uSelKind/uSelTimeRange/uSelAttrRange/uSelAttrChannel) dims points outside the active
// cross-panel selection -- evaluated per-vertex here rather than in JS, since re-testing every
// rendered point against the WorkingSet on every camera move would defeat LOD streaming
// entirely. Only 'time' and 'attribute' selections are wired into the shader; a spatial 'lasso'
// selection needs a variable-length polygon uniform (or a texture-encoded polygon), real
// complexity deferred to a later pass -- passing one here has no visible effect on this view
// (it still drives Panel A / the Inspector via the JS-side matches()/computeStats()).
function makeMaterial(): THREE.ShaderMaterial {
	const m = new THREE.ShaderMaterial({
		uniforms: {
			uGradient: { value: gradientTexture(props.colormap) },
			uRange: { value: new THREE.Vector2(0, 1) },
			uChannel: { value: CHANNEL_IDX[props.channel] ?? 1 },
			uSize: { value: props.pointSize || 1.5 },
			uSelKind: { value: 0 },                          // 0=none, 1=time, 2=attribute, 3=lasso
			uSelTimeRange: { value: new THREE.Vector2(0, 0) },
			uSelAttrRange: { value: new THREE.Vector2(0, 0) },
			uSelAttrChannel: { value: 0 },                   // 0=residZ, 1=tsaResid
		},
		vertexShader: `
			attribute float tsa_resid; attribute float resid_z;
			attribute float t;
			uniform vec2 uRange; uniform float uChannel; uniform float uSize;
			uniform float uSelKind;
			uniform vec2 uSelTimeRange;
			uniform vec2 uSelAttrRange;
			uniform float uSelAttrChannel;
			varying float vT;
			varying float vSelected;
			float pick(float i) {
				if (i < 0.5) return tsa_resid;
				return resid_z;
			}
			void main() {
				float v = pick(uChannel);
				vT = clamp((v - uRange.x) / max(1e-6, uRange.y - uRange.x), 0.0, 1.0);
				vSelected = 1.0;
				if (uSelKind > 0.5 && uSelKind < 1.5) {
					vSelected = (t >= uSelTimeRange.x && t <= uSelTimeRange.y) ? 1.0 : 0.0;
				} else if (uSelKind > 1.5 && uSelKind < 2.5) {
					float av = uSelAttrChannel < 0.5 ? resid_z : tsa_resid;
					vSelected = (av >= uSelAttrRange.x && av <= uSelAttrRange.y) ? 1.0 : 0.0;
				}
				gl_Position = projectionMatrix * modelViewMatrix * vec4(position.xy, 0.0, 1.0);
				gl_PointSize = uSize;
			}`,
		fragmentShader: `
			precision mediump float;
			uniform sampler2D uGradient; varying float vT; varying float vSelected;
			void main() {
				vec2 d = gl_PointCoord - vec2(0.5); if (dot(d, d) > 0.25) discard;
				vec3 c = texture2D(uGradient, vec2(vT, 0.5)).rgb;
				// Unselected points stay visible but muted -- an empty or wrong selection must
				// never read as "the map failed to load".
				float a = mix(0.15, 1.0, vSelected);
				gl_FragColor = vec4(c, a);
			}`,
	});
	(m as any).updateMaterial = () => { /* potree calls this per frame; fixed-size = no-op */ };
	return m;
}

// Shared teardown for the two GPU resources this component owns outright (potree-core owns
// `pco`'s own geometry buffers via its own dispose(), but never touches OUR material/texture).
// Used both on unmount and whenever octreePath swaps in a new octree -- without this, switching
// between operations leaked a full material + gradient texture + the old octree's geometry
// buffers on every switch, pushing the GL context toward exhaustion over a long session.
function disposeMaterial() {
	if (!material) return;
	(material.uniforms.uGradient.value as THREE.Texture | undefined)?.dispose();
	material.dispose();
	material = null;
}
function disposePco() {
	if (!pco) return;
	scene?.remove(pco);
	pco.dispose();
	pco = null;
}

let appliedLo = 0, appliedHi = 1;   // the colour range currently applied (for the figure export)
function applyRange() {
	if (!material) return;
	const auto = ranges[props.channel] || [0, 1];
	const lo = (props.cmin ?? null) !== null && Number.isFinite(props.cmin as number) ? (props.cmin as number) : auto[0];
	const hi = (props.cmax ?? null) !== null && Number.isFinite(props.cmax as number) ? (props.cmax as number) : auto[1];
	appliedLo = lo; appliedHi = hi > lo ? hi : lo + 1;
	material.uniforms.uRange.value.set(appliedLo, appliedHi);
	invalidate();
	emit('climits', { cmin: lo, cmax: hi });
}

function applySelection() {
	if (!material) return;
	const sel = props.selection;
	if (!sel) {
		material.uniforms.uSelKind.value = 0;
		invalidate();
		return;
	}
	material.uniforms.uSelKind.value = SEL_KIND_IDX[sel.kind];
	if (sel.kind === 'time') {
		material.uniforms.uSelTimeRange.value.set(sel.t0, sel.t1);
	} else if (sel.kind === 'attribute') {
		material.uniforms.uSelAttrRange.value.set(sel.min, sel.max);
		material.uniforms.uSelAttrChannel.value = sel.column === 'residZ' ? 0 : 1;
	}
	invalidate();
}

async function loadMeta(base: string) {
	try {
		// no-store: this metadata drives the colour limits; never risk a stale cached copy
		// (a pre-repatch metadata.json would show the wrong, un-clipped colour range).
		const res = await fetch(`${base}metadata.json`, { cache: 'no-store' });
		const meta = await res.json();
		// meta.attributes[].name is the octree's own (snake_case) LAS extra-dim name, e.g.
		// 'resid_z' -- ranges/ATTR_NAME are keyed by the prop's camelCase channel name, so match
		// via ATTR_NAME rather than `a.name in ranges` (which never matches, since 'resid_z' is
		// never a key of `ranges`; this silently left every channel on the [0,1] placeholder).
		const byAttrName = Object.fromEntries(Object.entries(ATTR_NAME).map(([k, v]) => [v, k]));
		for (const a of meta.attributes || []) {
			const propKey = byAttrName[a.name];
			if (propKey && Array.isArray(a.min) && Array.isArray(a.max)) {
				ranges[propKey] = [Number(a.min[0]), Number(a.max[0])];
			}
		}
	} catch { /* fall back to defaults */ }
}

async function load() {
	loading.value = true; error.value = null;
	// The octree host is configured, not assumed to be the SPA origin: the standalone app is
	// served from a different origin than the octree server, while the Directus module is
	// same-origin. The host supplies whichever applies.
	// "/octrees/diag/<octreePath>/" per this component's own prop contract above: octreePath is
	// the bare operation id that diag_path stores, and the "diag/" segment is this component's
	// to add -- it is what distinguishes the diagnostics octree from the raw spiral octree
	// FrmOctree.vue serves at /octrees/<octreePath>/. Dropping it silently loads that raw
	// octree instead (200, not 404) for any operation that has one.
	const base = `${useForceHost().octreeUrl}/diag/${props.octreePath}/`;
	try {
		await loadMeta(base);
		potree = new Potree();
		potree.maxNumNodesLoading = 12;   // parallelise node fetches so full-res streams in faster
		// "Full-res" must mean full res: budget the LOD to cover the whole octree (a small
		// headroom factor so the top level isn't shaved off), not a fixed 3M cap that left
		// large maps showing ~49%. Capped for GPU safety on the biggest maps.
		potree.pointBudget = props.totalPoints && props.totalPoints > 0
			? Math.min(Math.ceil(props.totalPoints * 1.05), props.budgetCap || 25_000_000)
			: 15_000_000;
		pco = await potree.loadPointCloud('metadata.json', base);
		// potree culls any octree node projecting smaller than minNodePixelSize (default
		// 50px) BEFORE the point budget is even considered — so at fit-view every deep
		// leaf is sub-50px and dropped, leaving only coarse levels (~8-50%). "Full-res"
		// must actually be full res, so drop the cutoff to ~1px; the budget above then
		// bounds the total. (Sub-pixel nodes contribute nothing visible anyway.)
		(pco as any).minNodePixelSize = props.minNodePx || 1;
		material = makeMaterial();
		(pco as any).material = material;
		applyRange();
		applySelection();
		scene!.add(pco);
		pco.updateMatrixWorld(true);
		frameCamera();
		loading.value = false;
	} catch (e: any) {
		error.value = e?.message || 'failed to load octree';
		loading.value = false;
	}
}

let baseSpan = 100;
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
	controls.addEventListener('change', invalidate);
	const loop = () => {
		raf = requestAnimationFrame(loop);
		controls!.update();
		if (pco && potree && renderer && camera) {
			const r = potree.updatePointClouds([pco], camera, renderer);
			const n = (r as any)?.numVisiblePoints ?? pointCount.value;
			if (n !== lastVisibleN) { lastVisibleN = n; needsRender = true; }   // nodes streamed in/out
			if (Math.abs(n - pointCount.value) > pointCount.value * 0.02 + 1) { pointCount.value = n; emit('points', n); }
			if (!needsRender) return;
			needsRender = false;
			renderer.render(scene!, camera);
		}
	};
	loop();
}

function sizeCanvas() {
	const canvas = canvasEl.value; if (!canvas) return;
	const r = canvas.getBoundingClientRect();
	cssW = Math.max(1, r.width); cssH = Math.max(1, r.height);
	renderer?.setSize(cssW, cssH, false);
}

let ro: ResizeObserver | undefined;
onMounted(() => {
	ro = new ResizeObserver(() => { sizeCanvas(); frameCamera(); });
	nextTick(() => { setupGL(); if (canvasEl.value) ro!.observe(canvasEl.value); load(); });
});
onBeforeUnmount(() => {
	if (raf) cancelAnimationFrame(raf);
	ro?.disconnect(); controls?.dispose();
	disposePco(); disposeMaterial();
	try { renderer?.forceContextLoss(); } catch { /* ignore */ }   // release the GL context (not freed by dispose())
	renderer?.dispose();
});

watch(() => props.octreePath, () => { disposePco(); disposeMaterial(); load(); });
watch(() => props.channel, () => { if (material) { material.uniforms.uChannel.value = CHANNEL_IDX[props.channel] ?? 1; applyRange(); } });
watch(() => props.colormap, () => {
	if (!material) return;
	(material.uniforms.uGradient.value as THREE.Texture | undefined)?.dispose();
	material.uniforms.uGradient.value = gradientTexture(props.colormap);
	invalidate();
});
watch(() => props.pointSize, () => { if (material) { material.uniforms.uSize.value = props.pointSize || 1.5; invalidate(); } });
watch(() => [props.cmin, props.cmax], applyRange);
watch(() => props.selection, applySelection, { deep: true });

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
// Export the current view as a formatted figure (client-side, no host round-trip). The render
// loop paints every frame + preserveDrawingBuffer is on, so the canvas pixels are live. Not
// wired to any UI trigger yet in this component (deferred, see plan) -- kept for parity with
// FrmOctree.vue, whose figure-export button this can be wired to in a later pass.
function exportViewport(filename: string, subtitle?: string) {
	const c = canvasEl.value;
	if (!c) return false;
	return exportFrmFigure({
		canvas: c, bounds: currentBounds(),
		cmin: appliedLo, cmax: appliedHi,
		colormap: props.colormap, axis: props.channel, subtitle, filename,
	});
}
defineExpose({ currentBounds, exportViewport });
</script>

<template>
	<div class="diag-octree">
		<div v-if="loading" class="fc-msg"><v-progress-circular indeterminate small /> streaming diagnostics…</div>
		<div v-else-if="error" class="fc-msg err"><v-icon name="error" small /> {{ error }}</div>
		<canvas v-show="!error" ref="canvasEl"></canvas>
		<span v-if="!loading && !error" class="fc-count">{{ pointCount.toLocaleString() }} pts (LOD)</span>
	</div>
</template>

<style scoped>
.diag-octree { position: relative; width: 100%; height: 100%; min-height: 160px; background: var(--plot-bg, #0b1020); border-radius: 6px; overflow: hidden; }
.diag-octree canvas { width: 100%; height: 100%; display: block; cursor: grab; touch-action: none; }
.diag-octree canvas:active { cursor: grabbing; }
.fc-msg { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; gap: 8px; color: var(--text-dim, #94a3b8); }
.fc-msg.err { color: var(--danger, #fca5a5); font-size: 12px; padding: 12px; text-align: center; }
.fc-count { position: absolute; right: 6px; bottom: 4px; font-size: 10px; color: var(--text-dim, rgba(255,255,255,0.6)); font-variant-numeric: tabular-nums; }
</style>
