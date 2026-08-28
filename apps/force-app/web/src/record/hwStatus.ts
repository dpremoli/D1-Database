// Shared, module-level mirror of the Record page's hardware/connectivity status (disk space,
// backend connection, backup stream). RecordPage.vue owns the actual polling/websocket state
// (scoped to its per-mount workspace instance) and just writes into this singleton on change;
// AppShell.vue's persistent sidebar — which renders on every route, not just Record — reads from
// here so the status chips can live in the sidebar instead of the page's own topbar.
import { reactive } from 'vue';

export const hwStatus = reactive({
	connected: false,
	diskFreeGb: -1,
	diskTotalGb: 0,
	backupEnabled: false,
	backupState: '',
	backupProgress: 0,
	backupConnected: false,
	backupError: null as string | null,
});
