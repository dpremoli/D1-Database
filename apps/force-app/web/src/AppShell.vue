<script setup lang="ts">
// Persistent app shell: a left vertical-tab sidebar (Record / Plot / Lab Amp / Settings) with the
// active section rendered in the main area. Replaces the old select page.
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import { authStore } from './authStore';
import { syncStatus } from './record/directusSync';
import { alarmController } from './record/alarms';

const router = useRouter();
const userName = computed(() => {
	const u = authStore.currentUser.value;
	if (!u) return '';
	return [u.first_name, u.last_name].filter(Boolean).join(' ') || u.email || '';
});
const nav = [
	{ to: '/record', icon: 'fiber_manual_record', label: 'Record' },
	{ to: '/plot', icon: 'insights', label: 'Plot' },
	{ to: '/labamp', icon: 'memory', label: 'Lab Amp' },
	{ to: '/settings', icon: 'settings', label: 'Settings' },
];
async function signOut() { await authStore.logout(); router.replace('/login'); }
// Multi-monitor: pop a section into its own window (e.g. Plot while recording). Same origin, so the
// new window shares the login; the recording backend is a single session but plotting is read-only.
function openWindow(to: string) { window.open(location.origin + to, '_blank', 'noopener,width=1500,height=950'); }
</script>

<template>
	<div class="shell">
		<nav class="sidebar">
			<div class="brand">
				<span class="brand-mark"><i class="dot fx"></i><i class="dot fy"></i><i class="dot fz"></i></span>
				<span class="brand-name">Force</span>
			</div>
			<div v-for="n in nav" :key="n.to" class="navrow">
				<router-link :to="n.to" class="navitem" active-class="active">
					<span class="material-symbols-rounded">{{ n.icon }}</span>
					<span class="lbl">{{ n.label }}</span>
					<span v-if="n.to === '/settings' && syncStatus.pending > 0" class="badge warn">{{ syncStatus.pending }}</span>
					<span v-if="n.to === '/record' && alarmController.tripped" class="badge alarm">!</span>
				</router-link>
				<button class="popout" title="Open in a new window (for a second monitor)" @click="openWindow(n.to)">
					<span class="material-symbols-rounded">open_in_new</span>
				</button>
			</div>
			<div class="spacer"></div>
			<div class="user">
				<span class="who">{{ userName }}</span>
				<button class="signout" title="Sign out" @click="signOut"><span class="material-symbols-rounded">logout</span></button>
			</div>
		</nav>
		<main class="content"><router-view /></main>
	</div>
</template>

<style scoped>
.shell { display: flex; min-height: 100vh; }
.sidebar { width: 96px; flex-shrink: 0; display: flex; flex-direction: column; align-items: stretch; gap: 4px; padding: 14px 8px; background: #0a0f1e; border-right: 1px solid var(--border); position: sticky; top: 0; height: 100vh; }
.brand { display: flex; flex-direction: column; align-items: center; gap: 5px; padding: 6px 0 12px; }
.brand-mark { display: inline-flex; gap: 3px; padding: 6px; border-radius: 8px; background: rgba(255,255,255,0.05); border: 1px solid var(--border); }
.dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; }
.dot.fx { background: var(--fx); } .dot.fy { background: var(--fy); } .dot.fz { background: var(--fz); }
.brand-name { font-size: 11px; font-weight: 700; letter-spacing: 0.06em; color: var(--text-dim); text-transform: uppercase; }
.navrow { position: relative; }
.popout { position: absolute; top: 4px; right: 4px; display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; padding: 0; border-radius: 6px; background: var(--surface-2); border: 1px solid var(--border); color: var(--text-dim); cursor: pointer; opacity: 0; transition: opacity 0.14s; }
.popout .material-symbols-rounded { font-size: 13px; }
.navrow:hover .popout { opacity: 1; }
.popout:hover { color: var(--accent); }
.navitem { position: relative; display: flex; flex-direction: column; align-items: center; gap: 3px; padding: 10px 4px; border-radius: 10px; color: var(--text-dim); text-decoration: none; transition: background 0.14s, color 0.14s; }
.navitem .material-symbols-rounded { font-size: 22px; }
.navitem .lbl { font-size: 10.5px; font-weight: 600; }
.navitem:hover { background: var(--surface); color: var(--text); }
.navitem.active { background: rgba(56,189,248,0.14); color: var(--accent); }
.badge { position: absolute; top: 6px; right: 18px; min-width: 15px; height: 15px; padding: 0 3px; display: inline-flex; align-items: center; justify-content: center; font-size: 9.5px; font-weight: 700; border-radius: 8px; }
.badge.warn { color: #0b1020; background: #fbbf24; }
.badge.alarm { color: #fff; background: #ef4444; animation: b 0.8s infinite; }
@keyframes b { 50% { opacity: 0.35; } }
.spacer { flex: 1; }
.user { display: flex; flex-direction: column; align-items: center; gap: 6px; padding-top: 8px; border-top: 1px solid var(--border); }
.who { font-size: 9.5px; color: var(--text-dim); text-align: center; word-break: break-word; max-width: 82px; }
.signout { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 8px; background: var(--surface); border: 1px solid var(--border); color: var(--text); cursor: pointer; }
.signout:hover { background: var(--surface-2); }
.content { flex: 1; min-width: 0; }
</style>
