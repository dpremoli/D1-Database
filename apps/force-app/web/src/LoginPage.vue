<script setup lang="ts">
import { ref } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { authStore } from './authStore';
import { getConfig } from './config';

const router = useRouter();
const route = useRoute();

const email = ref('');
const password = ref('');
const busy = ref(false);
const error = ref<string | null>(null);

async function submit() {
	if (busy.value) return;
	error.value = null;
	busy.value = true;
	try {
		await authStore.login(email.value.trim(), password.value);
		const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/select';
		router.replace(redirect);
	} catch (e: any) {
		const status = e?.response?.status;
		error.value = status === 401 ? 'Incorrect email or password.' : e?.message || 'Sign-in failed. Check the connection and try again.';
	} finally {
		busy.value = false;
	}
}
</script>

<template>
	<div class="login-wrap">
		<div class="login-aura" aria-hidden="true"></div>
		<form class="login-card" @submit.prevent="submit">
			<div class="brand">
				<span class="brand-mark">
					<i class="dot fx"></i><i class="dot fy"></i><i class="dot fz"></i>
				</span>
				<h1>Force App</h1>
			</div>
			<p class="subtitle">Sign in with your Directus account</p>

			<label class="field">
				<span>Email</span>
				<input v-model="email" type="email" autocomplete="username" required :disabled="busy" placeholder="you@example.com" />
			</label>

			<label class="field">
				<span>Password</span>
				<input v-model="password" type="password" autocomplete="current-password" required :disabled="busy" placeholder="••••••••" />
			</label>

			<p v-if="error" class="error"><span class="material-symbols-rounded">error</span>{{ error }}</p>

			<button class="submit" type="submit" :disabled="busy || !email || !password">
				<span v-if="busy" class="spinner"></span>
				<span>{{ busy ? 'Signing in…' : 'Sign in' }}</span>
			</button>

			<p class="host">{{ getConfig().directusUrl || 'same-origin' }}</p>
		</form>
	</div>
</template>

<style scoped>
.login-wrap {
	position: relative;
	min-height: 100vh;
	display: flex;
	align-items: center;
	justify-content: center;
	padding: 24px;
	background: radial-gradient(1200px 600px at 50% -10%, var(--bg-2), var(--bg));
	overflow: hidden;
}
.login-aura {
	position: absolute;
	width: 620px;
	height: 620px;
	border-radius: 50%;
	filter: blur(120px);
	opacity: 0.35;
	background: conic-gradient(from 180deg, var(--fx), var(--fz), var(--fy), var(--fx));
	pointer-events: none;
}
.login-card {
	position: relative;
	width: 100%;
	max-width: 380px;
	padding: 32px 30px 22px;
	background: rgba(17, 26, 51, 0.72);
	backdrop-filter: blur(14px);
	border: 1px solid var(--border);
	border-radius: var(--radius);
	box-shadow: 0 30px 80px rgba(0, 0, 0, 0.45);
}
.brand {
	display: flex;
	align-items: center;
	gap: 12px;
}
.brand h1 {
	margin: 0;
	font-size: 22px;
	letter-spacing: -0.01em;
}
.brand-mark {
	display: inline-flex;
	gap: 4px;
	padding: 8px;
	border-radius: 10px;
	background: rgba(255, 255, 255, 0.05);
	border: 1px solid var(--border);
}
.dot {
	width: 9px;
	height: 9px;
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
.subtitle {
	margin: 14px 0 22px;
	color: var(--text-dim);
	font-size: 13.5px;
}
.field {
	display: block;
	margin-bottom: 14px;
}
.field span {
	display: block;
	font-size: 12px;
	color: var(--text-dim);
	margin-bottom: 6px;
}
.field input {
	width: 100%;
	padding: 11px 13px;
	font-size: 14px;
	color: var(--text);
	background: rgba(0, 0, 0, 0.25);
	border: 1px solid var(--border);
	border-radius: 10px;
	outline: none;
	transition: border-color 0.15s, box-shadow 0.15s;
}
.field input:focus {
	border-color: var(--accent);
	box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.18);
}
.error {
	display: flex;
	align-items: center;
	gap: 6px;
	margin: 4px 0 12px;
	color: var(--danger);
	font-size: 13px;
}
.error .material-symbols-rounded {
	font-size: 18px;
}
.submit {
	width: 100%;
	display: inline-flex;
	align-items: center;
	justify-content: center;
	gap: 9px;
	margin-top: 6px;
	padding: 12px;
	font-size: 14.5px;
	font-weight: 600;
	color: var(--accent-ink);
	background: var(--accent);
	border: none;
	border-radius: 10px;
	cursor: pointer;
	transition: filter 0.15s, opacity 0.15s;
}
.submit:hover:not(:disabled) {
	filter: brightness(1.06);
}
.submit:disabled {
	opacity: 0.55;
	cursor: not-allowed;
}
.spinner {
	width: 15px;
	height: 15px;
	border-radius: 50%;
	border: 2px solid currentColor;
	border-top-color: transparent;
	animation: spin 0.7s linear infinite;
}
@keyframes spin {
	to {
		transform: rotate(360deg);
	}
}
.host {
	margin: 18px 0 0;
	text-align: center;
	font-size: 11px;
	color: var(--text-dim);
	opacity: 0.7;
	word-break: break-all;
}
</style>
