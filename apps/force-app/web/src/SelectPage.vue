<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import { authStore } from './authStore';

const router = useRouter();

const userName = computed(() => {
	const u = authStore.currentUser.value;
	if (!u) return '';
	return [u.first_name, u.last_name].filter(Boolean).join(' ') || u.email || '';
});

function go(section: 'plot' | 'record') {
	if (section === 'record') return; // Phase 2 — disabled
	router.push('/plot');
}

async function signOut() {
	await authStore.logout();
	router.replace('/login');
}
</script>

<template>
	<div class="select-wrap">
		<header class="topbar">
			<div class="brand">
				<span class="brand-mark"><i class="dot fx"></i><i class="dot fy"></i><i class="dot fz"></i></span>
				<span class="brand-name">Force App</span>
			</div>
			<div class="user">
				<span v-if="userName" class="who">{{ userName }}</span>
				<button class="signout" @click="signOut"><span class="material-symbols-rounded">logout</span>Sign out</button>
			</div>
		</header>

		<main class="choose">
			<h2>What would you like to do?</h2>
			<div class="cards">
				<button class="card active" @click="go('plot')">
					<span class="card-icon plotting"><span class="material-symbols-rounded">insights</span></span>
					<span class="card-title">Plotting &amp; Analysis</span>
					<span class="card-desc">Browse recorded cuts, inspect force &amp; FFT traces, and explore the FRM fingerprint maps.</span>
					<span class="card-go">Open<span class="material-symbols-rounded">arrow_forward</span></span>
				</button>

				<button class="card disabled" disabled aria-disabled="true">
					<span class="badge">Coming soon</span>
					<span class="card-icon recording"><span class="material-symbols-rounded">fiber_manual_record</span></span>
					<span class="card-title">Recording &amp; Acquisition</span>
					<span class="card-desc">Set up data streams, control the lab amplifier, live-plot the cut, and log runs to the database.</span>
					<span class="card-go muted">Phase 2</span>
				</button>
			</div>
		</main>
	</div>
</template>

<style scoped>
.select-wrap {
	min-height: 100vh;
	background: radial-gradient(1200px 600px at 50% -10%, var(--bg-2), var(--bg));
	display: flex;
	flex-direction: column;
}
.topbar {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 16px 22px;
	border-bottom: 1px solid var(--border);
}
.brand {
	display: flex;
	align-items: center;
	gap: 10px;
}
.brand-mark {
	display: inline-flex;
	gap: 3px;
	padding: 6px;
	border-radius: 8px;
	background: rgba(255, 255, 255, 0.05);
	border: 1px solid var(--border);
}
.dot {
	width: 7px;
	height: 7px;
	border-radius: 50%;
	display: inline-block;
}
.dot.fx {
	background: var(--fx);
}
.dot.fy {
	background: var(--fy);
}
.dot.fz {
	background: var(--fz);
}
.brand-name {
	font-weight: 600;
	letter-spacing: -0.01em;
}
.user {
	display: flex;
	align-items: center;
	gap: 14px;
}
.who {
	font-size: 13px;
	color: var(--text-dim);
}
.signout {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	padding: 7px 12px;
	font-size: 13px;
	color: var(--text);
	background: var(--surface);
	border: 1px solid var(--border);
	border-radius: 9px;
	cursor: pointer;
}
.signout:hover {
	background: var(--surface-2);
}
.signout .material-symbols-rounded {
	font-size: 17px;
}
.choose {
	flex: 1;
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	padding: 40px 24px 64px;
}
.choose h2 {
	font-size: 26px;
	font-weight: 650;
	letter-spacing: -0.02em;
	margin: 0 0 34px;
}
.cards {
	display: grid;
	grid-template-columns: repeat(2, minmax(0, 320px));
	gap: 22px;
	width: 100%;
	max-width: 680px;
}
@media (max-width: 640px) {
	.cards {
		grid-template-columns: 1fr;
	}
}
.card {
	position: relative;
	display: flex;
	flex-direction: column;
	align-items: flex-start;
	gap: 12px;
	padding: 26px 24px 22px;
	text-align: left;
	background: rgba(17, 26, 51, 0.6);
	border: 1px solid var(--border);
	border-radius: var(--radius);
	color: var(--text);
	cursor: pointer;
	transition: transform 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;
}
.card.active:hover {
	transform: translateY(-3px);
	border-color: var(--accent);
	box-shadow: 0 20px 50px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(56, 189, 248, 0.25);
}
.card.disabled {
	opacity: 0.55;
	cursor: not-allowed;
}
.card-icon {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	width: 46px;
	height: 46px;
	border-radius: 12px;
}
.card-icon .material-symbols-rounded {
	font-size: 26px;
}
.card-icon.plotting {
	background: rgba(56, 189, 248, 0.16);
	color: var(--accent);
}
.card-icon.recording {
	background: rgba(220, 38, 38, 0.16);
	color: #f87171;
}
.card-title {
	font-size: 17px;
	font-weight: 640;
}
.card-desc {
	font-size: 13px;
	line-height: 1.5;
	color: var(--text-dim);
}
.card-go {
	display: inline-flex;
	align-items: center;
	gap: 5px;
	margin-top: 4px;
	font-size: 13px;
	font-weight: 600;
	color: var(--accent);
}
.card-go.muted {
	color: var(--text-dim);
}
.card-go .material-symbols-rounded {
	font-size: 17px;
}
.badge {
	position: absolute;
	top: 14px;
	right: 14px;
	font-size: 10.5px;
	font-weight: 700;
	text-transform: uppercase;
	letter-spacing: 0.05em;
	padding: 3px 8px;
	border-radius: 20px;
	color: var(--text-dim);
	background: rgba(255, 255, 255, 0.06);
	border: 1px solid var(--border);
}
</style>
