<script setup lang="ts">
// Live FRM fingerprint: a three.js point cloud that accumulates the spiral as frames arrive from
// the RecordClient. Preallocated buffers filled incrementally (partial GPU upload of only the new
// points each frame). Colour uses the plotting app's shared COLORMAPS (viridis by default),
// mapping each point's chosen-axis force symmetrically around zero by the running |c| max.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import * as THREE from 'three';
import type { RecordClient } from './liveClient';
import { COLORMAPS } from '../force/liveCloud';

const props = withDefaults(defineProps<{ client: RecordClient; diam: number; colormap?: string }>(), {
	colormap: 'viridis',
});

const canvasEl = ref<HTMLCanvasElement | null>(null);
const CAP = 1_000_000;
let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.OrthographicCamera | null = null;
let geom: THREE.BufferGeometry | null = null;
let posAttr: THREE.BufferAttribute | null = null;
let colAttr: THREE.BufferAttribute | null = null;
let disc: THREE.CanvasTexture | null = null;
let raf = 0;
let uploaded = 0;
let cssW = 1, cssH = 1;

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
	const mat = new THREE.PointsMaterial({ size: 2.0, sizeAttenuation: false, vertexColors: true, map: disc, alphaTest: 0.5, transparent: false });
	scene.add(new THREE.Points(geom, mat));
	sizeCanvas(); frame();
	loop();
}

function sizeCanvas() {
	const c = canvasEl.value; if (!c || !renderer || !camera) return;
	const r = c.getBoundingClientRect();
	cssW = Math.max(1, r.width); cssH = Math.max(1, r.height);
	renderer.setSize(cssW, cssH, false);
	const half = (props.diam * 1.1) / 2;
	const aspect = cssW / cssH;
	camera.left = -half * (aspect >= 1 ? aspect : 1); camera.right = -camera.left;
	camera.top = half / (aspect >= 1 ? 1 : aspect); camera.bottom = -camera.top;
	camera.updateProjectionMatrix();
}

function frame() {
	const cm = COLORMAPS[props.colormap] || COLORMAPS.viridis;
	const fm = props.client.frm;
	// New run detected (buffers reset) -> clear our upload cursor.
	if (fm.count < uploaded) { uploaded = 0; geom!.setDrawRange(0, 0); }
	const from = uploaded, to = fm.count;
	if (to > from && posAttr && colAttr) {
		const cMax = Math.max(1e-6, fm.cAbsMax);
		const pos = posAttr.array as Float32Array;
		const col = colAttr.array as Float32Array;
		for (let i = from; i < to; i++) {
			pos[i * 3] = fm.xy[i * 2];
			pos[i * 3 + 1] = fm.xy[i * 2 + 1];
			pos[i * 3 + 2] = 0;
			const tnorm = Math.min(1, Math.max(0, (fm.c[i] + cMax) / (2 * cMax)));
			const [r, g, b] = cm(tnorm);
			col[i * 3] = r; col[i * 3 + 1] = g; col[i * 3 + 2] = b;
		}
		// Re-upload the attribute buffers (full upload — robust across three versions; point
		// counts in 2a are modest and this only runs on frames that actually added points).
		posAttr.needsUpdate = true; colAttr.needsUpdate = true;
		geom!.setDrawRange(0, to);
		uploaded = to;
	}
}

function loop() {
	raf = requestAnimationFrame(loop);
	frame();
	if (renderer && scene && camera) renderer.render(scene, camera);
}

// Reactive point count for the label (client.frm.count is a plain field; frameSeq bumps per frame).
const ptsLabel = computed(() => { void props.client.frameSeq.value; return props.client.frm.count; });

watch(() => props.diam, () => sizeCanvas());
onMounted(() => { setup(); window.addEventListener('resize', sizeCanvas); });
onBeforeUnmount(() => {
	cancelAnimationFrame(raf);
	window.removeEventListener('resize', sizeCanvas);
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
