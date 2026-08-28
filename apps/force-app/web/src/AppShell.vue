<script setup lang="ts">
// Persistent app shell: a left vertical-tab sidebar (Record / Plot / Lab Amp / Settings) with the
// active section rendered in the main area. Replaces the old select page.
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';
import { authStore } from './authStore';
import { syncStatus } from './record/directusSync';
import { hwStatus } from './record/hwStatus';
import { alarmController } from './record/alarms';
import { appUrl } from './appUrl';

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
	{ to: '/nidaq', icon: 'cable', label: 'NI-DAQ' },
	{ to: '/settings', icon: 'settings', label: 'Settings' },
];
async function signOut() { await authStore.logout(); router.replace('/login'); }
// Collapsed to a 3-vertical-dot handle at the left-middle of the screen most of the time — it
// overlays the page rather than reserving a permanent 96px column, sliding out on hover so it
// doesn't compete with the recording panels for width.
const expanded = ref(false);
// Multi-monitor: pop a section into its own window (e.g. Plot while recording). Same origin, so the
// new window shares the login; the recording backend is a single session but plotting is read-only.
function openWindow(to: string) { window.open(appUrl(to), '_blank', 'noopener,width=1500,height=950'); }
</script>

<template>
	<div class="shell">
		<nav class="sidebar" :class="{ expanded }" @mouseenter="expanded = true" @mouseleave="expanded = false">
			<div class="trigger" v-show="!expanded">
				<span class="vdot fx"></span><span class="vdot fy"></span><span class="vdot fz"></span>
			</div>
			<div class="navwrap" v-show="expanded">
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
				<div class="statuswrap">
					<div v-if="syncStatus.pending > 0 || syncStatus.lastError" class="chip" :class="syncStatus.pending > 0 ? 'warn' : 'err'"
						:title="syncStatus.lastError || `${syncStatus.pending} run record(s) queued offline`">
						<span class="material-symbols-rounded">{{ syncStatus.pending > 0 ? 'cloud_queue' : 'error' }}</span>
						<span v-if="syncStatus.pending > 0" class="chip-lbl">{{ syncStatus.pending }}</span>
					</div>
					<div v-if="hwStatus.diskFreeGb >= 0" class="chip" :class="{ warn: hwStatus.diskFreeGb < 10, crit: hwStatus.diskFreeGb < 5 }"
						:title="`${hwStatus.diskFreeGb.toFixed(1)} GB free of ${hwStatus.diskTotalGb.toFixed(0)} GB`">
						<span class="material-symbols-rounded">hard_drive</span>
						<span class="chip-lbl">{{ hwStatus.diskFreeGb < 100 ? hwStatus.diskFreeGb.toFixed(1) : Math.round(hwStatus.diskFreeGb) }} GB</span>
					</div>
					<div v-if="hwStatus.backupEnabled" class="chip"
						:class="{ warn: hwStatus.backupState === 'paused', ok: hwStatus.backupState === 'streaming', err: hwStatus.backupState === 'error' }"
						:title="hwStatus.backupError || `Backup ${hwStatus.backupState || 'idle'} · ${hwStatus.backupProgress.toFixed(0)}%`">
						<span class="material-symbols-rounded">{{ hwStatus.backupConnected ? 'cloud_done' : 'cloud_off' }}</span>
						<span v-if="hwStatus.backupState === 'streaming'" class="chip-lbl">{{ hwStatus.backupProgress.toFixed(0) }}%</span>
					</div>
					<div v-if="hwStatus.diskFreeGb >= 0" class="chip" :class="{ ok: hwStatus.connected }" :title="hwStatus.connected ? 'Backend connected' : 'Backend disconnected'">
						<span class="material-symbols-rounded">{{ hwStatus.connected ? 'sensors' : 'sensors_off' }}</span>
					</div>
				</div>
				<div class="user">
					<span class="who">{{ userName }}</span>
					<button class="signout" title="Sign out" @click="signOut"><span class="material-symbols-rounded">logout</span></button>
				</div>
			</div>
		</nav>
		<main class="content"><router-view /></main>
	</div>
</template>

<style scoped>
.shell { display: flex; min-height: 100vh; }
.sidebar {
	position: fixed; top: 50%; left: 0; transform: translateY(-50%); z-index: 200;
	width: 30px; height: 120px; overflow: hidden;
	display: flex; flex-direction: column; align-items: stretch; gap: 4px; padding: 8px 2px;
	background: var(--bg-2); border-top: 1px solid var(--border); border-right: 1px solid var(--border); border-bottom: 1px solid var(--border);
	border-radius: 0 14px 14px 0;
	transition: width 0.16s ease, height 0.16s ease, border-radius 0.16s ease, top 0.16s ease, transform 0.16s ease, padding 0.16s ease;
}
.sidebar.expanded { top: 0; transform: translateY(0); width: 96px; height: 100vh; padding: 8px; border-radius: 0; box-shadow: 8px 0 28px rgba(0,0,0,0.28); }
.trigger { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 5px; flex: 1; }
.vdot { width: 5px; height: 5px; border-radius: 50%; flex-shrink: 0; }
.vdot.fx { background: var(--fx); } .vdot.fy { background: var(--fy); } .vdot.fz { background: var(--fz); }
.navwrap { display: flex; flex-direction: column; flex: 1; min-height: 0; gap: 4px; }
.brand { display: flex; flex-direction: column; align-items: center; gap: 5px; padding: 0 0 8px; flex-shrink: 0; }
.brand-mark { display: inline-flex; gap: 3px; padding: 6px; border-radius: 8px; background: rgba(255,255,255,0.05); border: 1px solid var(--border); }
.dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; }
.dot.fx { background: var(--fx); } .dot.fy { background: var(--fy); } .dot.fz { background: var(--fz); }
.brand-name { font-size: 11px; font-weight: 700; letter-spacing: 0.06em; color: var(--text-dim); text-transform: uppercase; }
.navrow { position: relative; flex-shrink: 0; }
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
.statuswrap { display: flex; flex-direction: column; align-items: center; gap: 4px; flex-shrink: 0; }
.chip { display: inline-flex; align-items: center; justify-content: center; gap: 3px; width: 100%; padding: 4px 2px; border-radius: 7px; font-size: 9.5px; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--text-dim); border: 1px solid var(--border); }
.chip .material-symbols-rounded { font-size: 15px; }
.chip.ok { color: #4ade80; }
.chip.warn { color: #fbbf24; background: rgba(251,191,36,0.1); border-color: rgba(251,191,36,0.3); }
.chip.crit { color: #ef4444; background: rgba(239,68,68,0.1); border-color: rgba(239,68,68,0.3); animation: alarmpulse 0.9s ease-in-out infinite; }
.chip.err { color: var(--danger); background: rgba(239,68,68,0.1); border-color: rgba(239,68,68,0.3); }
@keyframes alarmpulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
.user { display: flex; flex-direction: column; align-items: center; gap: 6px; padding-top: 8px; border-top: 1px solid var(--border); }
.who { font-size: 9.5px; color: var(--text-dim); text-align: center; word-break: break-word; max-width: 82px; }
.signout { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 8px; background: var(--surface); border: 1px solid var(--border); color: var(--text); cursor: pointer; }
.signout:hover { background: var(--surface-2); }
/* The sidebar is fixed/overlaid — it expands over the page on hover rather than pushing content —
   so content needs no reserved margin at all; the collapsed left-middle dot handle sits on top of it. */
.content { flex: 1; min-width: 0; }
</style>
