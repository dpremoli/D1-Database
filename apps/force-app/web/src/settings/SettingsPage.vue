<script setup lang="ts">
// App settings with sub-tabs for things that don't need surfacing on the working pages.
import { ref } from 'vue';
import { useRoute } from 'vue-router';
import GeneralSettings from './GeneralSettings.vue';
import AlarmsSettings from './AlarmsSettings.vue';
import ConnectivitySettings from './ConnectivitySettings.vue';
import BackupSettings from './BackupSettings.vue';
import LogsSettings from './LogsSettings.vue';
import CapturesSettings from './CapturesSettings.vue';

const tabs = [
	{ id: 'general', label: 'General', icon: 'tune' },
	{ id: 'alarms', label: 'Safety Alarms', icon: 'warning' },
	{ id: 'connectivity', label: 'Connectivity', icon: 'network_check' },
	{ id: 'backup', label: 'Live Backup', icon: 'cloud_upload' },
	{ id: 'captures', label: 'Local Captures', icon: 'folder' },
	{ id: 'logs', label: 'Logs', icon: 'receipt_long' },
];
const VALID_TABS = ['general', 'alarms', 'connectivity', 'backup', 'captures', 'logs'] as const;
type SettingsTab = (typeof VALID_TABS)[number];

const route = useRoute();
const requestedTab = route.query.tab as string | undefined;
const initialTab: SettingsTab = VALID_TABS.includes(requestedTab as SettingsTab)
	? (requestedTab as SettingsTab)
	: 'general';
const active = ref<SettingsTab>(initialTab);
</script>

<template>
	<div class="settings">
		<header class="head"><h1>Settings</h1></header>
		<div class="body" :class="{ wide: active === 'logs' }">
			<nav class="subtabs">
				<button v-for="t in tabs" :key="t.id" class="subtab" :class="{ on: active === t.id }" @click="active = t.id as any">
					<span class="material-symbols-rounded">{{ t.icon }}</span>{{ t.label }}
				</button>
			</nav>
			<section class="pane">
				<GeneralSettings v-if="active === 'general'" />
				<AlarmsSettings v-else-if="active === 'alarms'" />
				<ConnectivitySettings v-else-if="active === 'connectivity'" />
				<BackupSettings v-else-if="active === 'backup'" />
				<CapturesSettings v-else-if="active === 'captures'" />
				<LogsSettings v-else-if="active === 'logs'" />
			</section>
		</div>
	</div>
</template>

<style scoped>
.settings { min-height: 100vh; background: radial-gradient(1200px 600px at 50% -10%, var(--bg-2), var(--bg)); }
.head { padding: 20px 26px 12px; border-bottom: 1px solid var(--border); }
.head h1 { margin: 0; font-size: 22px; letter-spacing: -0.01em; }
/* Form-shaped panes read better narrow; the log viewer needs the width, so the cap is
   lifted for that tab only. */
.body { display: flex; gap: 24px; padding: 22px 26px; max-width: 1000px; }
.body.wide { max-width: 1500px; }
.subtabs { display: flex; flex-direction: column; gap: 4px; width: 190px; flex-shrink: 0; }
.subtab { display: flex; align-items: center; gap: 9px; padding: 10px 12px; font-size: 13.5px; color: var(--text-dim); background: transparent; border: 1px solid transparent; border-radius: 9px; cursor: pointer; text-align: left; }
.subtab .material-symbols-rounded { font-size: 19px; }
.subtab:hover { background: var(--surface); color: var(--text); }
.subtab.on { background: rgba(56,189,248,0.14); color: var(--accent); border-color: rgba(56,189,248,0.28); }
.pane { flex: 1; min-width: 0; }
</style>
