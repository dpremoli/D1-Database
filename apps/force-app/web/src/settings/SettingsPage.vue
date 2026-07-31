<script setup lang="ts">
// App settings with sub-tabs for things that don't need surfacing on the working pages.
import { ref } from 'vue';
import GeneralSettings from './GeneralSettings.vue';
import AlarmsSettings from './AlarmsSettings.vue';

const tabs = [
	{ id: 'general', label: 'General', icon: 'tune' },
	{ id: 'alarms', label: 'Safety Alarms', icon: 'warning' },
];
const active = ref<'general' | 'alarms'>('general');
</script>

<template>
	<div class="settings">
		<header class="head"><h1>Settings</h1></header>
		<div class="body">
			<nav class="subtabs">
				<button v-for="t in tabs" :key="t.id" class="subtab" :class="{ on: active === t.id }" @click="active = t.id as any">
					<span class="material-symbols-rounded">{{ t.icon }}</span>{{ t.label }}
				</button>
			</nav>
			<section class="pane">
				<GeneralSettings v-if="active === 'general'" />
				<AlarmsSettings v-else-if="active === 'alarms'" />
			</section>
		</div>
	</div>
</template>

<style scoped>
.settings { min-height: 100vh; background: radial-gradient(1200px 600px at 50% -10%, var(--bg-2), var(--bg)); }
.head { padding: 20px 26px 12px; border-bottom: 1px solid var(--border); }
.head h1 { margin: 0; font-size: 22px; letter-spacing: -0.01em; }
.body { display: flex; gap: 24px; padding: 22px 26px; max-width: 1000px; }
.subtabs { display: flex; flex-direction: column; gap: 4px; width: 190px; flex-shrink: 0; }
.subtab { display: flex; align-items: center; gap: 9px; padding: 10px 12px; font-size: 13.5px; color: var(--text-dim); background: transparent; border: 1px solid transparent; border-radius: 9px; cursor: pointer; text-align: left; }
.subtab .material-symbols-rounded { font-size: 19px; }
.subtab:hover { background: var(--surface); color: var(--text); }
.subtab.on { background: rgba(56,189,248,0.14); color: var(--accent); border-color: rgba(56,189,248,0.28); }
.pane { flex: 1; min-width: 0; }
</style>
