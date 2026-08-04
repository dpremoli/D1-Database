<script setup lang="ts">
// Live RPM meter: a radial gauge + numeric readout vs the programmed target, plus a rolling
// sparkline of recent RPM. Reads the live stream's rpm each frame (no per-sample reactivity).
import { computed, ref, watch } from 'vue';
import { useWorkspace } from '../workspace';

const w = useWorkspace();
const hist = ref<number[]>([]);
const MAXH = 160;
watch(() => w.client.frameSeq.value, () => {
	if (w.st.state !== 'recording') return;
	hist.value.push(w.st.rpm);
	if (hist.value.length > MAXH) hist.value.shift();
});

const rpm = computed(() => w.st.rpm || 0);
const target = computed(() => w.cfg.rpm || 0);
const max = computed(() => Math.max(target.value * 1.25, rpm.value * 1.1, 100));
const overTarget = computed(() => target.value > 0 && rpm.value > target.value * 1.02);

// Gauge geometry: a 240° arc from -120°..+120°.
const CX = 100, CY = 96, R = 78, SWEEP = 240, START = -120;
function polar(deg: number, r = R): [number, number] {
	const a = ((deg - 90) * Math.PI) / 180;
	return [CX + r * Math.cos(a), CY + r * Math.sin(a)];
}
function arc(a0: number, a1: number, r = R): string {
	const [x0, y0] = polar(a0, r), [x1, y1] = polar(a1, r);
	return `M ${x0} ${y0} A ${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1} ${y1}`;
}
const frac = computed(() => Math.min(1, rpm.value / max.value));
const valDeg = computed(() => START + SWEEP * frac.value);
const targetDeg = computed(() => START + SWEEP * Math.min(1, target.value / max.value));
const needle = computed(() => polar(valDeg.value, R - 10));
const targetTick = computed(() => ({ a: polar(targetDeg.value, R + 2), b: polar(targetDeg.value, R - 14) }));

const spark = computed(() => {
	const h = hist.value;
	if (h.length < 2) return '';
	const mx = Math.max(...h, target.value, 1);
	return h.map((v, i) => `${(i / (h.length - 1)) * 200},${38 - (v / mx) * 34}`).join(' ');
});
</script>

<template>
	<div class="rpm-panel">
		<svg viewBox="0 0 200 150" class="gauge">
			<path :d="arc(START, START + SWEEP)" class="track" />
			<path :d="arc(START, valDeg)" class="value" :class="{ over: overTarget }" />
			<line v-if="target > 0" :x1="targetTick.a[0]" :y1="targetTick.a[1]" :x2="targetTick.b[0]" :y2="targetTick.b[1]" class="target" />
			<line :x1="CX" :y1="CY" :x2="needle[0]" :y2="needle[1]" class="needle" :class="{ over: overTarget }" />
			<circle :cx="CX" :cy="CY" r="5" class="hub" />
			<text :x="CX" :y="CY - 8" class="big" :class="{ over: overTarget }">{{ Math.round(rpm) }}</text>
			<text :x="CX" :y="CY + 8" class="unit">RPM</text>
		</svg>
		<div class="foot">
			<span class="target-lbl">target {{ Math.round(target) }}</span>
			<svg viewBox="0 0 200 40" class="spark" preserveAspectRatio="none">
				<polyline :points="spark" />
			</svg>
		</div>
	</div>
</template>

<style scoped>
.rpm-panel { display: flex; flex-direction: column; height: 100%; align-items: center; justify-content: center; gap: 6px; }
.gauge { width: 100%; max-width: 260px; height: auto; }
.track { fill: none; stroke: rgba(255,255,255,0.08); stroke-width: 12; stroke-linecap: round; }
.value { fill: none; stroke: #4ade80; stroke-width: 12; stroke-linecap: round; transition: none; }
.value.over { stroke: #ef4444; }
.target { stroke: #fbbf24; stroke-width: 2.5; }
.needle { stroke: #e2e8f0; stroke-width: 3; stroke-linecap: round; }
.needle.over { stroke: #ef4444; }
.hub { fill: #e2e8f0; }
.big { fill: #e2e8f0; font-size: 30px; font-weight: 700; text-anchor: middle; font-variant-numeric: tabular-nums; }
.big.over { fill: #f87171; }
.unit { fill: var(--text-dim); font-size: 11px; text-anchor: middle; letter-spacing: 0.08em; }
.foot { width: 100%; max-width: 260px; }
.target-lbl { font-size: 11px; color: #fbbf24; }
.spark { width: 100%; height: 40px; }
.spark polyline { fill: none; stroke: #60a5fa; stroke-width: 1.5; vector-effect: non-scaling-stroke; }
</style>
