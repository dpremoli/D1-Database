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
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { Potree, type PointCloudOctree } from 'potree-core';
import { COLORMAPS } from './liveCloud';

const props = defineProps<{
	octreePath: string;                       // served subdir: /octrees/<octreePath>/
	axis: 'Fx' | 'Fy' | 'Fz';
	colormap: string;
	pointSize: number;
	cmin?: number | null;
	cmax?: number | null;
	zSeries?: 'none' | 'Fx' | 'Fy' | 'Fz';    // drive the Z axis from a force series -> true 3D
	zScale?: number;                          // height exaggeration as a fraction of the x/y span
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
// per-axis value ranges (from the octree metadata) for auto colour limits
const ranges: Record<string, [number, number]> = { Fx: [0, 1], Fy: [0, 1], Fz: [0, 1] };
const AXIS_IDX: Record<string, number> = { Fx: 0, Fy: 1, Fz: 2 };

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

// One material reads all three force attributes; a uAxis uniform selects which drives
// the colour, and uRange normalises it before the viridis lookup.
function makeMaterial(): THREE.ShaderMaterial {
	const m = new THREE.ShaderMaterial({
		uniforms: {
			uGradient: { value: gradientTexture(props.colormap) },
			uRange: { value: new THREE.Vector2(0, 1) },
			uAxis: { value: AXIS_IDX[props.axis] ?? 2 },
			uSize: { value: props.pointSize || 1.5 },
			uZAxis: { value: -1 },                        // -1 = flat (2D); 0/1/2 = Fx/Fy/Fz drive Z
			uZRange: { value: new THREE.Vector2(0, 1) },
			uZScale: { value: 0 },                        // world-unit height for the [0,1]-normalised Z
		},
		vertexShader: `
			attribute float Fx; attribute float Fy; attribute float Fz;
			uniform vec2 uRange; uniform float uAxis; uniform float uSize;
			uniform float uZAxis; uniform vec2 uZRange; uniform float uZScale;
			varying float vT;
			float pick(float i) { return i < 0.5 ? Fx : (i < 1.5 ? Fy : Fz); }
			void main() {
				float v = pick(uAxis);
				vT = clamp((v - uRange.x) / max(1e-6, uRange.y - uRange.x), 0.0, 1.0);
				float z = 0.0;
				if (uZAxis >= 0.0) {
					float zv = pick(uZAxis);
					z = (clamp((zv - uZRange.x) / max(1e-6, uZRange.y - uZRange.x), 0.0, 1.0) - 0.5) * uZScale;
				}
				gl_Position = projectionMatrix * modelViewMatrix * vec4(position.xy, z, 1.0);
				gl_PointSize = uSize;
			}`,
		fragmentShader: `
			precision mediump float;
			uniform sampler2D uGradient; varying float vT;
			void main() {
				vec2 d = gl_PointCoord - vec2(0.5); if (dot(d, d) > 0.25) discard;
				gl_FragColor = vec4(texture2D(uGradient, vec2(vT, 0.5)).rgb, 1.0);
			}`,
	});
	(m as any).updateMaterial = () => { /* potree calls this per frame; fixed-size = no-op */ };
	return m;
}

function applyRange() {
	if (!material) return;
	const auto = ranges[props.axis] || [0, 1];
	const lo = (props.cmin ?? null) !== null && Number.isFinite(props.cmin as number) ? (props.cmin as number) : auto[0];
	const hi = (props.cmax ?? null) !== null && Number.isFinite(props.cmax as number) ? (props.cmax as number) : auto[1];
	material.uniforms.uRange.value.set(lo, hi > lo ? hi : lo + 1);
	emit('climits', { cmin: lo, cmax: hi });
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
		controls.enableRotate = true;
	} else {
		material.uniforms.uZScale.value = 0;
		controls.enableRotate = false;
		frameCamera();   // snap back to a clean top-down view when flattening
	}
}

async function loadMeta(base: string) {
	try {
		const res = await fetch(`${base}metadata.json`);
		const meta = await res.json();
		for (const a of meta.attributes || []) {
			if (a.name in ranges && Array.isArray(a.min) && Array.isArray(a.max)) {
				ranges[a.name] = [Number(a.min[0]), Number(a.max[0])];
			}
		}
	} catch { /* fall back to defaults */ }
}

async function load() {
	loading.value = true; error.value = null;
	const base = `${window.location.origin}/octrees/${props.octreePath}/`;
	try {
		await loadMeta(base);
		potree = new Potree();
		potree.pointBudget = 3_000_000;
		pco = await potree.loadPointCloud('metadata.json', base);
		material = makeMaterial();
		(pco as any).material = material;
		applyRange();
		scene!.add(pco);
		pco.updateMatrixWorld(true);
		frameCamera();
		applyZ();
		loading.value = false;
	} catch (e: any) {
		error.value = e?.message || 'failed to load octree';
		loading.value = false;
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
	const loop = () => {
		raf = requestAnimationFrame(loop);
		controls!.update();
		if (pco && potree && renderer && camera) {
			const r = potree.updatePointClouds([pco], camera, renderer);
			const n = (r as any)?.numVisiblePoints ?? pointCount.value;
			if (Math.abs(n - pointCount.value) > pointCount.value * 0.02 + 1) { pointCount.value = n; emit('points', n); }
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
	ro?.disconnect(); controls?.dispose(); material?.dispose(); renderer?.dispose();
});

watch(() => props.octreePath, () => { if (pco) { scene?.remove(pco); pco = null; } load(); });
watch(() => props.axis, () => { if (material) { material.uniforms.uAxis.value = AXIS_IDX[props.axis] ?? 2; applyRange(); } });
watch(() => props.colormap, () => { if (material) material.uniforms.uGradient.value = gradientTexture(props.colormap); });
watch(() => props.pointSize, () => { if (material) material.uniforms.uSize.value = props.pointSize || 1.5; });
watch(() => [props.cmin, props.cmax], applyRange);
watch(() => [props.zSeries, props.zScale], applyZ);
</script>

<template>
	<div class="frm-octree">
		<div v-if="loading" class="fc-msg"><v-progress-circular indeterminate small /> streaming full-res…</div>
		<div v-else-if="error" class="fc-msg err"><v-icon name="error" small /> {{ error }}</div>
		<canvas v-show="!error" ref="canvasEl"></canvas>
		<span v-if="!loading && !error" class="fc-count">{{ pointCount.toLocaleString() }} pts (LOD)</span>
	</div>
</template>

<style scoped>
.frm-octree { position: relative; width: 100%; height: 100%; min-height: 160px; background: #0b1020; border-radius: 6px; overflow: hidden; }
.frm-octree canvas { width: 100%; height: 100%; display: block; cursor: grab; touch-action: none; }
.frm-octree canvas:active { cursor: grabbing; }
.fc-msg { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; gap: 8px; color: #94a3b8; }
.fc-msg.err { color: #fca5a5; font-size: 12px; padding: 12px; text-align: center; }
.fc-count { position: absolute; right: 6px; bottom: 4px; font-size: 10px; color: rgba(255,255,255,0.6); font-variant-numeric: tabular-nums; }
</style>
