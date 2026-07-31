<script setup lang="ts">
// FRM panel: the live accumulating spiral while recording; the captured fingerprint (rendered via
// the plotting FrmCloud from the backend's D1LC) once done.
import { useWorkspace } from '../workspace';
import LiveFrm from '../LiveFrm.vue';
import FrmCloud from '../../force/FrmCloud.vue';
const w = useWorkspace();
</script>

<template>
	<div class="frm-panel">
		<div class="frm-controls">
			<div class="segmode">
				<button class="segbtn fx" :class="{ on: w.plot.frmAxis === 'Fx' }" @click="w.plot.frmAxis = 'Fx'">Fx</button>
				<button class="segbtn fy" :class="{ on: w.plot.frmAxis === 'Fy' }" @click="w.plot.frmAxis = 'Fy'">Fy</button>
				<button class="segbtn fz" :class="{ on: w.plot.frmAxis === 'Fz' }" @click="w.plot.frmAxis = 'Fz'">Fz</button>
			</div>
		</div>
		<div class="frm-body">
		<template v-if="!w.isDone.value">
			<LiveFrm :client="w.client" :diam="w.cfg.diam" :colormap="w.plot.colormap" :point-size="w.plot.pointSize" />
		</template>
		<template v-else>
			<FrmCloud v-if="w.finishedCache.value" cache-file-id="" :cache-override="w.finishedCache.value"
				:axis="w.plot.frmAxis" :feed="w.finishedCache.value.feed" :diam="w.finishedCache.value.diam" :inner-diam="w.cfg.inner_diam"
				speed-mode="measured" :rpm="w.cfg.rpm" :vc="0" :time-scale="1" :ppr="w.cfg.ppr"
				:crop-start-sec="w.finishedCache.value.csSec" :crop-end-sec="w.finishedCache.value.ceSec"
				:stride="1" :gridding="false" :grid-n="600" :point-size="w.plot.pointSize" :colormap="w.plot.colormap" pane-label="captured" />
			<div v-else class="loading">Loading capture…</div>
		</template>
		</div>
	</div>
</template>

<style scoped>
.frm-panel { display: flex; flex-direction: column; height: 100%; min-height: 0; gap: 8px; }
.frm-controls { display: flex; justify-content: flex-end; }
.frm-body { flex: 1; min-height: 0; }
.frm-body > * { height: 100%; }
.loading { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--text-dim); }
</style>
