<script setup lang="ts">
/*
 * Potree integration SPIKE — Phase B: load an actual Potree 2.0 octree (built by
 * PotreeConverter 2.1.1 from a synthetic spiral LAS) via potree-core, stream it with
 * LOD, top-down orthographic, and confirm it renders. Served by a loopback CORS static
 * server (scratchpad/cors_server.py on :8000). This retires the serving + streaming
 * unknown before building the real .mat→octree pipeline.
 */
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { Potree, type PointCloudOctree } from 'potree-core';

// Served same-origin by Caddy (/octrees/*) so Directus's CSP allows streaming it.
// Real op 9fa1f0e9 octree (1.93M pts, built by the host .mat->octree pipeline).
const OCTREE_BASE = `${window.location.origin}/octrees/9fa1f0e9-373c-5de6-af48-57f1b4df87bb/`;

const host = ref<HTMLDivElement | null>(null);
const status = ref<string[]>([]);
function log(s: string) { status.value.push(s); }

// viridis anchor LUT → a 256×1 gradient texture our custom material samples.
const VIRIDIS: [number, number, number][] = [
	[0.267004, 0.004874, 0.329415], [0.282623, 0.140926, 0.457517], [0.253935, 0.265254, 0.529983],
	[0.206756, 0.371758, 0.553117], [0.163625, 0.471133, 0.558148], [0.127568, 0.566949, 0.550556],
	[0.134692, 0.658636, 0.517649], [0.266941, 0.748751, 0.440573], [0.477504, 0.821444, 0.318195],
	[0.741388, 0.873449, 0.149561], [0.993248, 0.906157, 0.143936],
];
function viridisTexture(): THREE.DataTexture {
	const N = 256, data = new Uint8Array(N * 4);
	for (let i = 0; i < N; i++) {
		const x = i / (N - 1), s = x * 10, k = Math.min(9, Math.floor(s)), f = s - k;
		const a = VIRIDIS[k], b = VIRIDIS[k + 1];
		data[i * 4] = 255 * (a[0] + (b[0] - a[0]) * f);
		data[i * 4 + 1] = 255 * (a[1] + (b[1] - a[1]) * f);
		data[i * 4 + 2] = 255 * (a[2] + (b[2] - a[2]) * f);
		data[i * 4 + 3] = 255;
	}
	const t = new THREE.DataTexture(data, N, 1, THREE.RGBAFormat);
	t.minFilter = THREE.LinearFilter; t.magFilter = THREE.LinearFilter; t.needsUpdate = true;
	return t;
}

// Our own point material: colour by the `intensity` attribute (the force scalar) through
// the viridis gradient, in-shader. This bypasses potree-core 2.0.15's broken 2.0-octree
// colour pipeline (new_format hard-codes vColor=rgba + its rgba decoder is buggy). potree
// stays responsible only for octree LOD/streaming; WE own colour, exactly like Phase 1.
function makeViridisMaterial(range: [number, number]): THREE.ShaderMaterial {
	return new THREE.ShaderMaterial({
		uniforms: {
			uGradient: { value: viridisTexture() },
			uRange: { value: new THREE.Vector2(range[0], range[1]) },
			uSize: { value: 2.0 },
		},
		vertexShader: `
			attribute float intensity;
			uniform vec2 uRange; uniform float uSize;
			varying float vT;
			void main() {
				vT = clamp((intensity - uRange.x) / max(1.0, uRange.y - uRange.x), 0.0, 1.0);
				gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
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
}

let renderer: THREE.WebGLRenderer | null = null;
let controls: OrbitControls | null = null;
let raf = 0;

async function waitForHost(tries = 30): Promise<HTMLDivElement> {
	for (let i = 0; i < tries; i++) {
		if (host.value) return host.value;
		await new Promise((r) => requestAnimationFrame(() => r(null)));
	}
	throw new Error('stage element never mounted');
}

onMounted(async () => {
	try {
		log(`three r${THREE.REVISION}`);
		await nextTick();
		const el = await waitForHost();
		const W = el.clientWidth || 800, H = el.clientHeight || 600;

		const scene = new THREE.Scene();
		scene.background = new THREE.Color(0x0b1020);
		const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 1e6);
		cam.position.set(0, 0, 1000);

		renderer = new THREE.WebGLRenderer({ antialias: true });
		renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
		renderer.setSize(W, H);
		el.appendChild(renderer.domElement);
		log(`webgl: ${renderer.getContext() ? 'ok' : 'FAILED'}`);

		controls = new OrbitControls(cam, renderer.domElement);
		controls.enableRotate = false;   // 2D top-down
		controls.mouseButtons = { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };

		// ---- load the Potree 2.0 octree via potree-core ----
		const potree = new Potree();
		potree.pointBudget = 1_500_000;
		log(`loading octree from ${OCTREE_BASE}metadata.json …`);
		let pco: PointCloudOctree;
		try {
			pco = await potree.loadPointCloud('metadata.json', OCTREE_BASE);
		} catch (e: any) {
			log(`ERROR octree load: ${e?.message || e}`);
			return;
		}
		scene.add(pco);
		// Colour by a SCALAR attribute (the force, stored in `intensity`) through a
		// viridis gradient — the real-build path (recolour/re-range without touching the
		// octree). Not baked RGB.
		// Replace potree-core's (broken-for-colour) material with our own viridis-by-
		// intensity material BEFORE the first updatePointClouds, so every streamed node
		// is created with it. potree keeps doing LOD; we do colour.
		const viridisMat = makeViridisMaterial([0, 65535]);
		// potree-core calls material.updateMaterial(...) per frame to push LOD uniforms;
		// our fixed-size material doesn't need them, so stub it to a no-op.
		(viridisMat as any).updateMaterial = () => { /* fixed-size: no per-frame LOD uniforms */ };
		(pco as any).material = viridisMat;
		log(`custom viridis material installed (colour by intensity)`);
		log(`octree attrs: ${(pco.pcoGeometry as any)?.pointAttributes?.attributes?.map((a: any) => a.name).join(',') ?? '?'}`);
		pco.updateMatrixWorld(true);
		log(`octree loaded: ${pco.pcoGeometry?.root ? 'root node ok' : 'no root'}`);

		// frame the ortho camera to the cloud bounds (top-down)
		const box = pco.boundingBox.clone().applyMatrix4(pco.matrixWorld);
		const c = box.getCenter(new THREE.Vector3()), sz = box.getSize(new THREE.Vector3());
		const span = (Math.max(sz.x, sz.y) || 100) * 1.1, aspect = W / H;
		cam.left = -span / 2 * aspect; cam.right = span / 2 * aspect; cam.top = span / 2; cam.bottom = -span / 2;
		cam.position.set(c.x, c.y, c.z + 1e4); cam.lookAt(c.x, c.y, c.z); cam.updateProjectionMatrix();
		controls.target.set(c.x, c.y, c.z); controls.update();
		log(`bounds x[${box.min.x.toFixed(0)},${box.max.x.toFixed(0)}] y[${box.min.y.toFixed(0)},${box.max.y.toFixed(0)}]`);

		let logged = false;
		const loop = () => {
			raf = requestAnimationFrame(loop);
			controls!.update();
			const r = potree.updatePointClouds([pco], cam, renderer!);
			if (!logged && r && (r as any).numVisiblePoints > 0) {
				log(`streaming: ${(r as any).numVisiblePoints.toLocaleString()} visible points`);
				logged = true;
			}
			renderer!.render(scene, cam);
		};
		loop();
		log('render loop running — drag to pan, wheel to zoom');
	} catch (e: any) {
		log(`ERROR: ${e?.message || e}`);
	}
});

onBeforeUnmount(() => { if (raf) cancelAnimationFrame(raf); controls?.dispose(); renderer?.dispose(); });
</script>

<template>
	<private-view title="Potree Spike">
		<div class="wrap">
			<div class="bar">
				<strong>Potree octree spike (Phase B)</strong>
				<span>PotreeConverter octree · potree-core LOD streaming · top-down · drag=pan wheel=zoom</span>
			</div>
			<div class="stage" ref="host"></div>
			<ul class="log"><li v-for="(s, i) in status" :key="i" :class="{ err: s.startsWith('ERROR') }">{{ s }}</li></ul>
		</div>
	</private-view>
</template>

<style scoped>
.wrap { padding: 16px 20px 40px; }
.bar { display: flex; flex-direction: column; gap: 2px; margin-bottom: 10px; }
.bar span { font-size: 12px; color: var(--theme--foreground-subdued, #6b7684); }
.stage { width: 100%; height: 70vh; min-height: 460px; border-radius: 12px; overflow: hidden; background: #0b1020; }
.stage :deep(canvas) { display: block; width: 100%; height: 100%; cursor: grab; }
.log { margin: 10px 0 0; padding: 8px 12px; list-style: none; background: var(--theme--background-subdued, #f7f9fb); border-radius: 8px; font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 12px; }
.log li { line-height: 1.6; } .log li.err { color: #b91c1c; font-weight: 700; }
</style>
