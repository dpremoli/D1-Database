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
import { Potree, type PointCloudOctree, PointColorType, VIRIDIS } from 'potree-core';

// Served same-origin by Caddy (/octrees/*) so Directus's CSP allows streaming it.
const OCTREE_BASE = `${window.location.origin}/octrees/spiral/`;

const host = ref<HTMLDivElement | null>(null);
const status = ref<string[]>([]);
function log(s: string) { status.value.push(s); }

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
		const m: any = pco.material;
		m.size = 1.5;
		m.pointSizeType = 0;                             // FIXED px
		m.pointColorType = PointColorType.INTENSITY_GRADIENT;
		m.intensityRange = [0, 65535];                  // spike intensity = fval*65535
		m.gradient = VIRIDIS;
		if (typeof m.updateShaderSource === 'function') m.updateShaderSource();
		m.needsUpdate = true;
		log(`material: ${m?.constructor?.name} pointColorType=${m.pointColorType} hasUpdateFn=${typeof m.updateShaderSource === 'function'}`);
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
