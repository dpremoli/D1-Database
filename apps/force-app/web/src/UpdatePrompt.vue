<script setup lang="ts">
// "A new version is ready" card (#197). Replaces the native dialog that popped up over the login
// password field, took focus, and installed on Enter. This one is non-modal, takes no focus, has no
// key handlers, and lives in AppShell, so it can never appear on /login.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import type { UpdateStatus } from './electronBridge';
import { dismissedUpdateVersion, shouldShowUpdatePrompt } from './updatePrompt';

const props = defineProps<{ recording: boolean }>();

const route = useRoute();
const status = ref<UpdateStatus>({ state: 'idle' });
const notice = ref('');
const installing = ref(false);

const show = computed(() => shouldShowUpdatePrompt({
	status: status.value,
	dismissedVersion: dismissedUpdateVersion.value,
	recording: props.recording,
	routePath: route.path,
}));
const version = computed(() => ('version' in status.value ? status.value.version : ''));
const notes = computed(() => (status.value.state === 'downloaded' ? status.value.notes : ''));

function notNow() {
	if (status.value.state === 'downloaded') dismissedUpdateVersion.value = status.value.version;
	notice.value = '';
}

async function install() {
	if (!window.forceApp || installing.value) return;
	installing.value = true;
	notice.value = '';
	try {
		// The main process re-checks for a running or still-saving recording and refuses if so.
		const res = await window.forceApp.installUpdate();
		if (!res.ok) notice.value = res.reason || 'could not install right now';
	} catch (e: any) {
		notice.value = e?.message || 'could not install right now';
	} finally {
		installing.value = false;
	}
}

let unsubscribe: (() => void) | null = null;
let gone = false;
onMounted(async () => {
	const bridge = window.forceApp;
	if (!bridge) return; // browser build: no updater
	// Subscribe first so a push that lands while get-info is in flight is not overwritten by the
	// older snapshot; the snapshot covers an update that finished downloading before this mounted
	// (for instance while the login page was showing).
	let pushed = false;
	unsubscribe = bridge.onUpdateStatus((s) => { pushed = true; status.value = s; });
	try {
		const info = await bridge.getUpdateInfo();
		if (!gone && !pushed) status.value = info.status;
	} catch { /* no status yet: stay hidden */ }
	if (gone) { unsubscribe?.(); unsubscribe = null; }
});
onBeforeUnmount(() => { gone = true; unsubscribe?.(); unsubscribe = null; });
</script>

<template>
	<aside v-if="show" class="upd" role="status" aria-live="polite" aria-label="Update ready">
		<div class="upd-head">
			<span class="material-symbols-rounded upd-icon">system_update_alt</span>
			<div class="upd-title">
				<b v-if="status.state === 'installing'">Installing version {{ version }}…</b>
				<b v-else>Version {{ version }} is ready</b>
				<span class="upd-sub" v-if="status.state === 'installing'">The app will close and reopen in a few seconds.</span>
				<span class="upd-sub" v-else>Downloaded. Install it when it suits you; it is also under Settings &gt; About.</span>
			</div>
		</div>
		<template v-if="status.state === 'downloaded'">
			<div v-if="notes" class="upd-notes">
				<div class="upd-notes-h">What's new</div>
				<pre>{{ notes }}</pre>
			</div>
			<p v-if="notice" class="upd-err">
				<span class="material-symbols-rounded">error</span> {{ notice }}
			</p>
			<div class="upd-actions">
				<button type="button" class="btn sm" :disabled="installing" @click="notNow">Not now</button>
				<button type="button" class="btn sm primary" :disabled="installing" @click="install">
					<span class="material-symbols-rounded">restart_alt</span> Restart and update
				</button>
			</div>
		</template>
	</aside>
</template>

<style scoped>
.upd {
	position: fixed; right: 16px; bottom: 16px; z-index: 180; width: min(380px, calc(100vw - 32px));
	display: flex; flex-direction: column; gap: 10px; padding: 14px 16px;
	color: var(--text); background: var(--bg-2); border: 1px solid var(--border-2); border-radius: var(--radius);
	box-shadow: 0 12px 36px rgba(0, 0, 0, 0.35);
}
.upd-head { display: flex; gap: 10px; align-items: flex-start; }
.upd-icon { color: var(--accent); font-size: var(--icon-lg); }
.upd-title { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.upd-title b { font-size: var(--fs-md); }
.upd-sub { font-size: var(--fs-sm); color: var(--text-dim); }
.upd-notes { border: 1px solid var(--border); border-radius: 10px; background: var(--surface); padding: 8px 10px; }
.upd-notes-h { font-size: var(--fs-xs); font-weight: 600; color: var(--text-dim); margin-bottom: 4px; }
.upd-notes pre { margin: 0; max-height: 160px; overflow: auto; white-space: pre-wrap; word-break: break-word; font: inherit; font-size: var(--fs-sm); }
.upd-err { display: flex; gap: 6px; align-items: center; margin: 0; font-size: var(--fs-sm); color: var(--danger); }
.upd-err .material-symbols-rounded { font-size: var(--icon-xs); }
.upd-actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
