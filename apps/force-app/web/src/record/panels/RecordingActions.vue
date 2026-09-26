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
		<div v-else class="actions-row">
			<!-- Acquisition's processing toggles: moved here from a Details card so they're checked
				 in the moment right before Start, not folded away. Bound to w.recordingPrefs, the
				 persisted singleton shared with Settings > Recording — not w.cfg/w.converge, which
				 only carry per-session/transient state now (see recordingPrefs.ts). -->
			<div v-if="w.source.value !== 'replay'" class="segproc">
				<button type="button" :class="{ on: w.recordingPrefs.frmFromCut }" :disabled="w.locked.value"
					title="Detect cut start — live FRM begins at the cut" @click="w.recordingPrefs.frmFromCut = !w.recordingPrefs.frmFromCut">
					<span class="material-symbols-rounded">flag</span>Cut start
				</button>
				<button type="button" :class="{ on: w.recordingPrefs.driftComp }" :disabled="w.locked.value"
					title="Drift compensation — saved outputs only, raw stays raw" @click="w.recordingPrefs.driftComp = !w.recordingPrefs.driftComp">
					<span class="material-symbols-rounded">compare_arrows</span>Drift
				</button>
				<button type="button" :class="{ on: w.recordingPrefs.convergeEnabled }" :disabled="w.locked.value"
					title="Converging auto-range — tune per-channel ranges between cuts" @click="w.recordingPrefs.convergeEnabled = !w.recordingPrefs.convergeEnabled">
					<span class="material-symbols-rounded">tune</span>Converge
				</button>
			</div>
			<div class="actions">
				<button v-if="!w.locked.value" class="btn start" :disabled="w.busy.value || !w.st.connected" @click="w.start()">
					<span class="material-symbols-rounded">fiber_manual_record</span> Start
				</button>
				<button v-else class="btn stop" :disabled="w.busy.value || w.isFinalizing.value" @click="w.stop()">
					<span class="material-symbols-rounded">stop</span> {{ w.isFinalizing.value ? 'Finalizing…' : 'Stop' }}
				</button>
				<button v-if="w.isDone.value" class="btn ghost" @click="w.newRun()">New</button>
			</div>
		</div>
		<div v-if="w.mode.value !== 'playback' && w.source.value !== 'replay'" class="proc-notes">
			<p v-if="w.recordingPrefs.convergeEnabled && w.source.value !== 'nidaq'" class="hint">Applies live only with the NI-DAQ source; on sim/replay it just previews the recommendation.</p>
			<p v-if="w.converge.status" class="sync" :class="w.converge.busy ? 'warn' : 'ok'"><span class="material-symbols-rounded">tune</span>{{ w.converge.status }}</p>
		</div>
		<p v-if="w.errMsg.value" class="err">{{ w.errMsg.value }}</p>
		<p v-if="w.st.state === 'error' && w.st.error" class="err">{{ w.st.error.split('\n')[0] }}</p>
	</div>
</template>

<style scoped>
.actions-wrap { display: flex; flex-direction: column; gap: 4px; }
.actions-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.actions { display: flex; justify-content: flex-end; gap: 8px; flex-shrink: 0; }
.btn { display: inline-flex; align-items: center; gap: 6px; padding: 9px 14px; font-size: 13.5px; font-weight: 600; border: none; border-radius: 8px; cursor: pointer; }
.btn .material-symbols-rounded { font-size: 18px; }
.btn.start { background: #22c55e; color: #05210f; }
.btn.stop { background: #ef4444; color: #2a0808; }
.btn.ghost { background: var(--surface); color: var(--text); border: 1px solid var(--border); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
/* Acquisition's processing toggles — relocated from a Details card (see RecordingOptions.vue). */
.segproc { display: flex; min-width: 0; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.segproc button { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 3px; padding: 6px 8px; background: rgba(255,255,255,0.03); border: none; border-right: 1px solid var(--border); color: var(--text-dim); font-size: 9.5px; font-weight: 600; letter-spacing: 0.01em; cursor: pointer; }
.segproc button:last-child { border-right: none; }
.segproc button.on { color: var(--accent); background: color-mix(in srgb, var(--accent) 14%, transparent); }
.segproc button:disabled { opacity: 0.5; cursor: not-allowed; }
.segproc .material-symbols-rounded { font-size: 16px; }
.proc-notes { display: flex; flex-direction: column; gap: 4px; margin-top: 4px; }
.hint { font-size: 11.5px; color: var(--text-dim); margin: 0; }
.sync { display: flex; align-items: center; gap: 5px; font-size: 11.5px; margin: 0; }
.sync .material-symbols-rounded { font-size: 14px; }
.sync.ok { color: var(--ok); }
.sync.warn { color: var(--warn); }
.err { color: var(--danger); font-size: 12px; margin: 4px 0 0; }
</style>
