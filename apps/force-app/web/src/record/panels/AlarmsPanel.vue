<script setup lang="ts">
// Safety alarm config + live status. Thresholds persist; alarms evaluate on the live stream and
// latch until acknowledged. A Test button fires a synthetic alarm to confirm the alert works.
import { computed } from 'vue';
import { useWorkspace } from '../workspace';
const w = useWorkspace();
const a = w.alarms;
const rpmAuto = computed(() => Math.round(a.rpmLimit(w.cfg.rpm)));
function save() { a.saveCfg(); }
</script>

<template>
	<div class="alarms">
		<div class="row">
			<label class="chk"><input type="checkbox" v-model="a.config.forceEnabled" @change="save" /> High force</label>
			<label class="thr">≥ <input type="number" v-model.number="a.config.forceThreshold" :disabled="!a.config.forceEnabled" @change="save" /> N</label>
		</div>
		<div class="row">
			<label class="chk"><input type="checkbox" v-model="a.config.rpmEnabled" @change="save" /> High RPM</label>
			<label class="thr">≥ <input type="number" v-model.number="a.config.rpmThreshold" :disabled="!a.config.rpmEnabled" placeholder="auto" @change="save" /></label>
		</div>
		<p class="note">RPM limit: {{ a.config.rpmThreshold > 0 ? a.config.rpmThreshold : `auto ${rpmAuto} (spindle ×1.02)` }}</p>
		<label class="chk"><input type="checkbox" v-model="a.config.audioEnabled" @change="save" /> Audible alert</label>

		<div class="status" :class="{ tripped: a.active.length > 0 }">
			<template v-if="a.active.length">
				<div class="hdr"><span class="material-symbols-rounded">warning</span> {{ a.acknowledged.value ? 'Acknowledged' : 'ALARM' }}</div>
				<div v-for="al in a.active" :key="al.key" class="al">
					{{ al.label }}: <b>{{ al.value.toFixed(al.kind === 'rpm' ? 0 : 1) }}{{ al.kind === 'rpm' ? '' : ' N' }}</b>
					<span class="lim">(≥ {{ al.threshold.toFixed(0) }})</span>
				</div>
			</template>
			<div v-else class="ok"><span class="material-symbols-rounded">verified_user</span> No alarms</div>
		</div>

		<div class="btns">
			<button v-if="a.tripped" class="btn ack" @click="a.acknowledge()">Acknowledge</button>
			<button v-if="a.active.length" class="btn ghost" @click="a.reset()">Clear</button>
			<button class="btn ghost" @click="a.test()">Test</button>
		</div>
	</div>
</template>

<style scoped>
.alarms { display: flex; flex-direction: column; gap: 9px; }
.row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.chk { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text); cursor: pointer; }
.chk input { accent-color: var(--accent); }
.thr { display: flex; align-items: center; gap: 5px; font-size: 12px; color: var(--text-dim); }
.thr input { width: 76px; padding: 5px 7px; font-size: 12.5px; color: var(--text); background: rgba(0,0,0,0.25); border: 1px solid var(--border); border-radius: 6px; text-align: right; }
.thr input:disabled { opacity: 0.5; }
.note { font-size: 11px; color: var(--text-dim); margin: 0; }
.status { margin-top: 4px; padding: 9px 10px; border-radius: 8px; background: var(--surface); border: 1px solid var(--border); font-size: 12.5px; }
.status.tripped { border-color: #ef4444; background: rgba(239,68,68,0.1); }
.hdr { display: flex; align-items: center; gap: 6px; font-weight: 700; color: #f87171; margin-bottom: 4px; }
.hdr .material-symbols-rounded { font-size: 18px; }
.al { color: var(--text); }
.al .lim { color: var(--text-dim); }
.ok { display: flex; align-items: center; gap: 6px; color: #4ade80; }
.ok .material-symbols-rounded { font-size: 17px; }
.btns { display: flex; gap: 8px; }
.btn { padding: 7px 12px; font-size: 12.5px; font-weight: 600; border: none; border-radius: 8px; cursor: pointer; }
.btn.ack { background: #ef4444; color: #fff; }
.btn.ghost { background: var(--surface); color: var(--text); border: 1px solid var(--border); }
</style>
