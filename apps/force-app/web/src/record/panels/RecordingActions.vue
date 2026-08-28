<script setup lang="ts">
// Start/Stop (sim/nidaq) or the TransportBar (replay) — split out of RecordingOptions.vue so
// RecordPage.vue can hand it to PanelFrame's #footer slot and pin it to the bottom of the panel,
// always visible without scrolling past the metadata form.
import { useWorkspace } from '../workspace';
import TransportBar from './TransportBar.vue';

const w = useWorkspace();
</script>

<template>
	<div class="actions-wrap">
		<TransportBar v-if="w.mode.value === 'playback'" />
		<div v-else class="actions">
			<button v-if="!w.locked.value" class="btn start" :disabled="w.busy.value || !w.st.connected" @click="w.start()">
				<span class="material-symbols-rounded">fiber_manual_record</span> Start
			</button>
			<button v-else class="btn stop" :disabled="w.busy.value || w.isFinalizing.value" @click="w.stop()">
				<span class="material-symbols-rounded">stop</span> {{ w.isFinalizing.value ? 'Finalizing…' : 'Stop' }}
			</button>
			<button v-if="w.isDone.value" class="btn ghost" @click="w.newRun()">New</button>
		</div>
		<p v-if="w.errMsg.value" class="err">{{ w.errMsg.value }}</p>
		<p v-if="w.st.state === 'error' && w.st.error" class="err">{{ w.st.error.split('\n')[0] }}</p>
	</div>
</template>

<style scoped>
.actions-wrap { display: flex; flex-direction: column; gap: 4px; }
.actions { display: flex; gap: 8px; }
.btn { display: inline-flex; align-items: center; gap: 6px; padding: 9px 14px; font-size: 13.5px; font-weight: 600; border: none; border-radius: 8px; cursor: pointer; }
.btn .material-symbols-rounded { font-size: 18px; }
.btn.start { background: #22c55e; color: #05210f; }
.btn.stop { background: #ef4444; color: #2a0808; }
.btn.ghost { background: var(--surface); color: var(--text); border: 1px solid var(--border); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.err { color: var(--danger); font-size: 12px; margin: 4px 0 0; }
</style>
