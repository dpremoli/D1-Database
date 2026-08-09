<script setup lang="ts">
// FRM panel: the live accumulating spiral while recording; the captured fingerprint (rendered via
// the plotting FrmCloud from the backend's D1LC) once done.
import { useWorkspace } from '../workspace';
import LiveFrm from '../LiveFrm.vue';
import FrmCloud from '../../force/FrmCloud.vue';
import { appUrl } from '../../appUrl';
const w = useWorkspace();
const STRIDES = [1, 2, 5, 10, 25, 50];
function openLive() {
	const q = new URLSearchParams({ colormap: w.plot.colormap, pointSize: String(w.plot.pointSize), frmAxis: w.plot.frmAxis, stride: String(w.plot.liveFrmStride) });
	window.open(appUrl(`/live/frm?${q}`), '_blank', 'noopener,width=1200,height=1000');
}
</script>

<template>
	<div class="frm-panel">
		<div class="frm-controls">
			<div class="segmode">
				<button class="segbtn fx" :class="{ on: w.plot.frmAxis === 'Fx' }" @click="w.plot.frmAxis = 'Fx'">Fx</button>
				<button class="segbtn fy" :class="{ on: w.plot.frmAxis === 'Fy' }" @click="w.plot.frmAxis = 'Fy'">Fy</button>
				<button class="segbtn fz" :class="{ on: w.plot.frmAxis === 'Fz' }" @click="w.plot.frmAxis = 'Fz'">Fz</button>
			</div>
			<!-- Colormap + point size (folded in from the old Plot Options panel). -->
			<select class="cmap" v-model="w.plot.colormap" title="Colormap">
				<option v-for="m in ['viridis', 'inferno', 'grayscale']" :key="m">{{ m }}</option>
			</select>
			<input class="psize" type="range" min="1" max="5" step="0.1" v-model.number="w.plot.pointSize" :title="`Point size ${w.plot.pointSize.toFixed(1)}`" />
			<select v-if="!w.isDone.value" class="cmap" v-model.number="w.plot.liveFrmStride"
				title="Live map decimation — keep every Nth point. Raise this for long/dense cuts to keep the map responsive and under its point cap.">
				<option v-for="s in STRIDES" :key="s" :value="s">{{ s === 1 ? 'full res' : `1 / ${s}` }}</option>
			</select>
			<button class="popout" title="Pop out to a new window (second monitor) — open before Start" @click="openLive">
				<span class="material-symbols-rounded">open_in_new</span>
			</button>
		</div>
		<div class="frm-body">
		<FrmCloud v-if="w.isDone.value && w.finishedCache.value" cache-file-id="" :cache-override="w.finishedCache.value"
			:axis="w.plot.frmAxis" :feed="w.finishedCache.value.feed" :diam="w.finishedCache.value.diam" :inner-diam="w.cfg.inner_diam"
			speed-mode="measured" :rpm="w.cfg.rpm" :vc="0" :time-scale="1" :ppr="w.cfg.ppr"
			:crop-start-sec="w.finishedCache.value.csSec" :crop-end-sec="w.finishedCache.value.ceSec"
			:stride="1" :gridding="false" :grid-n="600" :point-size="w.plot.pointSize" :colormap="w.plot.colormap" pane-label="captured" />
		<LiveFrm v-else :client="w.client" :diam="w.cfg.diam" :colormap="w.plot.colormap" :point-size="w.plot.pointSize" :point-stride="w.plot.liveFrmStride" />
		</div>
	</div>
</template>

<style scoped>
.frm-panel { display: flex; flex-direction: column; height: 100%; min-height: 0; gap: 8px; }
.frm-controls { display: flex; justify-content: flex-end; align-items: center; gap: 8px; flex-wrap: wrap; }
.segmode { display: flex; gap: 4px; margin-right: auto; }
.segbtn { padding: 5px 10px; font-size: 12px; color: var(--text-dim); background: var(--surface); border: 1px solid var(--border); border-radius: 7px; cursor: pointer; }
.segbtn.on { background: var(--accent); color: var(--accent-ink); font-weight: 600; border-color: var(--accent); }
.segbtn.fx.on { background: #f87171; border-color: #f87171; color: #2a0808; }
.segbtn.fy.on { background: #4ade80; border-color: #4ade80; color: #05210f; }
.segbtn.fz.on { background: #60a5fa; border-color: #60a5fa; color: #05173a; }
.cmap { padding: 5px 7px; font-size: 12px; color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: 7px; }
.psize { width: 84px; accent-color: var(--accent); }
.popout { display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: 7px; background: var(--surface); border: 1px solid var(--border); color: var(--text-dim); cursor: pointer; }
.popout:hover { color: var(--accent); background: var(--surface-2); }
.popout .material-symbols-rounded { font-size: 15px; }
.frm-body { flex: 1; min-height: 0; }
.frm-body > * { height: 100%; }
.loading { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--text-dim); }
</style>
