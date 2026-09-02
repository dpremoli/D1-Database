<script setup lang="ts">
/*
 * Flat point render of the diag analysis cloud (the D1AN WorkingSet). Top-down orthographic,
 * one THREE.Points draw call, no LOD.
 *
 * Deviation from the design spec, deliberate: the spec assumed potree-core LOD ("the browser
 * never holds all N points"), but analyse() angular-resamples to 256/rev, so the analysis
 * cloud is 18k-~1M points across every baked cut measured this session -- small enough to hold
 * in one buffer, recolour instantly on a channel switch, and swap wholesale when a preview
 * returns. potree-core's streaming would add latency and complexity for no benefit at this
 * size. DiagOctreeView.vue (potree-core) is retained for Phase D-2's full-resolution view.
 *
 * Two colour modes: continuous channels go through a viridis gradient with an auto 1/99
 * percentile range; clusterMode reads cluster_id categorically from a 12-entry palette with
 * the noise "cluster" (id < 0) dimmed. A selection-dim path multiplies rgb by 0.15 for points
 * outside the active cross-panel selection -- computed in JS (cheap at <=1M) rather than in
 * the shader, since the selection can be any predicate.
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { COLORMAPS } from './liveCloud';
import { CLUSTER_PALETTE } from './clusterPalette';
import { matches } from './selection';
import type { ChannelKey, Selection, WorkingSet } from './selection';

const props = withDefaults(defineProps<{
	workingSet: WorkingSet | null;
	channel: ChannelKey;
	colormap?: string;
	pointSize?: number;
	selection?: Selection;
	clusterMode?: boolean;
}>(), { colormap: 'viridis', pointSize: 3, selection: null, clusterMode: false });

const emit = defineEmits<{ (e: 'climits', v: { cmin: number; cmax: number }): void }>();

const canvasEl = ref<HTMLCanvasElement | null>(null);
const error = ref<string | null>(null);

let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.OrthographicCamera | null = null;
let controls: OrbitControls | null = null;
let geom: THREE.BufferGeometry | null = null;
let material: THREE.ShaderMaterial | null = null;
let points: THREE.Points | null = null;
let raf = 0;
let cssW = 1, cssH = 1;
let needsRender = true;
function invalidate() { needsRender = true; }

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

function makeMaterial(): THREE.ShaderMaterial {
	const paletteFlat = new Float32Array(CLUSTER_PALETTE.flat());
	return new THREE.ShaderMaterial({
		transparent: true,
		uniforms: {
			uGradient: { value: gradientTexture(props.colormap) },
			uRange: { value: new THREE.Vector2(0, 1) },
			uSize: { value: props.pointSize },
			uCluster: { value: props.clusterMode ? 1 : 0 },
			uPalette: { value: paletteFlat },
			uSelActive: { value: 0 },
		},
		vertexShader: `
			attribute float aValue;
			attribute float aSelected;
			uniform sampler2D uGradient;
			uniform vec2 uRange;
			uniform float uSize;
			uniform float uCluster;
			uniform float uPalette[36];
			uniform float uSelActive;
			varying vec3 vColor;
			varying float vDim;
			void main() {
				if (uCluster > 0.5) {
					if (aValue < 0.0) {
						vColor = vec3(0.30);
					} else {
						int idx = int(mod(aValue, 12.0));
						vColor = vec3(uPalette[idx*3], uPalette[idx*3+1], uPalette[idx*3+2]);
					}
				} else {
					float u = clamp((aValue - uRange.x) / max(1e-6, uRange.y - uRange.x), 0.0, 1.0);
					vColor = texture2D(uGradient, vec2(u, 0.5)).rgb;
				}
				vDim = (uSelActive > 0.5 && aSelected < 0.5) ? 0.15 : 1.0;
				gl_PointSize = uSize;
				gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
			}
		`,
		fragmentShader: `
			precision mediump float;
			varying vec3 vColor;
			varying float vDim;
			void main() {
				vec2 d = gl_PointCoord - vec2(0.5);
				if (dot(d, d) > 0.25) discard;                 // round points
				gl_FragColor = vec4(vColor * vDim, vDim < 1.0 ? 0.5 : 1.0);
			}
		`,
	});
}

function percentileRange(a: Float32Array): [number, number] {
	if (a.length === 0) return [0, 1];
	const s = Float32Array.from(a).sort();
	const lo = s[Math.floor(0.01 * (s.length - 1))];
	const hi = s[Math.floor(0.99 * (s.length - 1))];
	return hi > lo ? [lo, hi] : [lo, lo + 1];
}

function channelArray(ws: WorkingSet, ch: ChannelKey): Float32Array {
	// CHANNEL_ACCESSOR is a per-index read; for the buffer we want the whole column. The
	// WorkingSet already stores each channel as a Float32Array under the camelCase key.
	return (ws as unknown as Record<string, Float32Array>)[ch];
}

function rebuildGeometry() {
	const ws = props.workingSet;
	geom?.dispose();
	if (!ws || ws.n === 0) { geom = null; if (points) points.visible = false; invalidate(); return; }
	geom = new THREE.BufferGeometry();
	const pos = new Float32Array(ws.n * 3);
	for (let i = 0; i < ws.n; i++) { pos[i * 3] = ws.x[i]; pos[i * 3 + 1] = ws.y[i]; pos[i * 3 + 2] = 0; }
	geom.setAttribute('position', new THREE.BufferAttribute(pos, 3));
	geom.setAttribute('aValue', new THREE.BufferAttribute(new Float32Array(ws.n), 1));
	geom.setAttribute('aSelected', new THREE.BufferAttribute(new Float32Array(ws.n), 1));
	if (points) { points.geometry = geom; points.visible = true; }
	packValue();
	packSelected();
	frameCamera();
}

function packValue() {
	const ws = props.workingSet;
	if (!geom || !ws || !material) return;
	const col = channelArray(ws, props.channel);
	const attr = geom.getAttribute('aValue') as THREE.BufferAttribute;
	(attr.array as Float32Array).set(col.subarray(0, ws.n));
	attr.needsUpdate = true;
	if (!props.clusterMode) {
		const [lo, hi] = percentileRange(col.subarray(0, ws.n));
		material.uniforms.uRange.value.set(lo, hi);
		emit('climits', { cmin: lo, cmax: hi });
	}
	invalidate();
}

function packSelected() {
	const ws = props.workingSet;
	if (!geom || !ws || !material) return;
	const attr = geom.getAttribute('aSelected') as THREE.BufferAttribute;
	const arr = attr.array as Float32Array;
	const active = props.selection != null;
	for (let i = 0; i < ws.n; i++) arr[i] = matches(ws, props.selection ?? null, i) ? 1 : 0;
	attr.needsUpdate = true;
	material.uniforms.uSelActive.value = active ? 1 : 0;
	invalidate();
}

function frameCamera() {
	const ws = props.workingSet;
	if (!camera || !controls || !ws || ws.n === 0) return;
	let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity;
	for (let i = 0; i < ws.n; i++) {
		if (ws.x[i] < xmin) xmin = ws.x[i]; if (ws.x[i] > xmax) xmax = ws.x[i];
		if (ws.y[i] < ymin) ymin = ws.y[i]; if (ws.y[i] > ymax) ymax = ws.y[i];
	}
	const cx = (xmin + xmax) / 2, cy = (ymin + ymax) / 2;
	const span = Math.max(xmax - xmin, ymax - ymin, 1) * 1.08;
	const aspect = cssW / cssH;
	camera.left = (-span / 2) * aspect; camera.right = (span / 2) * aspect;
	camera.top = span / 2; camera.bottom = -span / 2;
	camera.position.set(cx, cy, 1e5); camera.up.set(0, 1, 0); camera.lookAt(cx, cy, 0);
	camera.zoom = 1; camera.updateProjectionMatrix();
	controls.target.set(cx, cy, 0); controls.update();
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
	material = makeMaterial();
	points = new THREE.Points(new THREE.BufferGeometry(), material);
	points.frustumCulled = false;
	scene.add(points);
	rebuildGeometry();
	const loop = () => {
		raf = requestAnimationFrame(loop);
		controls!.update();
		if (!needsRender || !renderer || !camera || !scene) return;
		needsRender = false;
		renderer.render(scene, camera);
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
	nextTick(() => { setupGL(); if (canvasEl.value) ro!.observe(canvasEl.value); });
});
onBeforeUnmount(() => {
	if (raf) cancelAnimationFrame(raf);
	ro?.disconnect(); controls?.dispose();
	geom?.dispose(); material?.dispose();
	(material?.uniforms.uGradient.value as THREE.Texture | undefined)?.dispose();
	try { renderer?.forceContextLoss(); } catch { /* ignore */ }
	renderer?.dispose();
});

watch(() => props.workingSet, rebuildGeometry);
watch(() => props.channel, packValue);
watch(() => props.clusterMode, () => {
	if (material) material.uniforms.uCluster.value = props.clusterMode ? 1 : 0;
	packValue();
});
watch(() => props.colormap, () => {
	if (!material) return;
	(material.uniforms.uGradient.value as THREE.Texture | undefined)?.dispose();
	material.uniforms.uGradient.value = gradientTexture(props.colormap);
	invalidate();
});
watch(() => props.pointSize, () => { if (material) { material.uniforms.uSize.value = props.pointSize; invalidate(); } });
watch(() => props.selection, packSelected, { deep: true });
</script>

<template>
	<div class="diag-scatter">
		<div v-if="error" class="ds-msg err">{{ error }}</div>
		<div v-else-if="!workingSet" class="ds-msg">no analysis loaded</div>
		<canvas v-show="!error" ref="canvasEl"></canvas>
		<span v-if="workingSet && !error" class="ds-count">{{ workingSet.n.toLocaleString() }} pts</span>
	</div>
</template>

<style scoped>
.diag-scatter { position: relative; width: 100%; height: 100%; min-height: 160px; background: var(--plot-bg, #0b1020); border-radius: 6px; overflow: hidden; }
.diag-scatter canvas { width: 100%; height: 100%; display: block; cursor: grab; touch-action: none; }
.ds-msg { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: var(--text-dim, #94a3b8); font-size: 12px; }
.ds-msg.err { color: var(--danger, #fca5a5); }
.ds-count { position: absolute; right: 8px; bottom: 6px; font-size: 10px; color: var(--text-dim, #94a3b8); background: rgba(0,0,0,0.35); padding: 1px 5px; border-radius: 4px; font-variant-numeric: tabular-nums; }
</style>
