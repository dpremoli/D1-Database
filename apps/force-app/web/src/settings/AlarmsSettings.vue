<script setup lang="ts">
// Safety-alarm thresholds (the app-wide controller the Record page evaluates on the live stream).
import { alarmController } from '../record/alarms';
const a = alarmController;
function save() { a.saveCfg(); }
</script>

<template>
	<div class="alarms">
		<h2>Safety alarms</h2>
		<p class="lead">Evaluated on the live force stream while recording. When a threshold is breached the
			alarm latches (with a full-screen banner + optional tone on the Record page) until acknowledged.</p>

		<div class="grp">
			<label class="chk"><input type="checkbox" v-model="a.config.forceEnabled" @change="save" /> High-force alarm</label>
			<label class="thr">Trip at ≥ <input type="number" v-model.number="a.config.forceThreshold" :disabled="!a.config.forceEnabled" @change="save" /> N (per-axis peak)</label>
			<p class="hint">The MATLAB app tripped at a ~400 N peak; set to a safe fraction of your dynamometer / setup limit.</p>
		</div>

		<div class="grp">
			<label class="chk"><input type="checkbox" v-model="a.config.rpmEnabled" @change="save" /> High-RPM alarm</label>
			<label class="thr">Trip at ≥ <input type="number" v-model.number="a.config.rpmThreshold" :disabled="!a.config.rpmEnabled" placeholder="0 = auto" @change="save" /> RPM</label>
			<p class="hint">0 = auto: the configured spindle speed × 1.02 (matches the MATLAB app). Set an explicit value to cap regardless of the programmed RPM.</p>
		</div>

		<div class="grp">
			<label class="chk"><input type="checkbox" v-model="a.config.audioEnabled" @change="save" /> Audible alert (looping tone)</label>
		</div>

		<button class="btn ghost" @click="a.test()">Test alarm</button>
	</div>
</template>

<style scoped>
.alarms { max-width: 620px; }
h2 { margin: 0 0 4px; font-size: 16px; }
.lead { margin: 0 0 18px; font-size: 13px; color: var(--text-dim); line-height: 1.5; }
.grp { margin-bottom: 18px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
.chk { display: flex; align-items: center; gap: 8px; font-size: 14px; color: var(--text); cursor: pointer; margin-bottom: 8px; }
.chk input { accent-color: var(--accent); }
.thr { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-dim); }
.thr input { width: 90px; padding: 6px 9px; font-size: 13px; color: var(--text); background: rgba(0,0,0,0.25); border: 1px solid var(--border); border-radius: 7px; text-align: right; }
.thr input:disabled { opacity: 0.5; }
.hint { font-size: 11.5px; color: var(--text-dim); margin: 6px 0 0; line-height: 1.5; }
.btn.ghost { padding: 9px 16px; font-size: 13px; font-weight: 600; color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: 8px; cursor: pointer; }
</style>
