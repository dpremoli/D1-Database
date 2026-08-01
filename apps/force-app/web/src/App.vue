<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue';

// Best-effort offline indicator (Phase 1). Plotting needs the network to reach Directus; when
// the browser reports offline we surface a clear banner rather than letting requests hang
// silently. (Full offline plotting — a local data mirror — is deferred to a later phase.)
const online = ref(navigator.onLine);
function setOnline() {
	online.value = true;
}
function setOffline() {
	online.value = false;
}
onMounted(() => {
	window.addEventListener('online', setOnline);
	window.addEventListener('offline', setOffline);
});
onBeforeUnmount(() => {
	window.removeEventListener('online', setOnline);
	window.removeEventListener('offline', setOffline);
});
</script>

<template>
	<div class="app-root">
		<transition name="fade">
			<div v-if="!online" class="offline-banner">
				<span class="material-symbols-rounded">cloud_off</span>
				Offline — the database is unreachable. Plotting needs a connection; reconnect to continue.
			</div>
		</transition>
		<router-view />
	</div>
</template>

<style scoped>
.app-root {
	min-height: 100vh;
}
.offline-banner {
	position: fixed;
	top: 0;
	left: 0;
	right: 0;
	z-index: 1000;
	display: flex;
	align-items: center;
	justify-content: center;
	gap: 8px;
	padding: 8px 14px;
	font-size: 13px;
	font-weight: 600;
	color: #7c2d12;
	background: #fed7aa;
	border-bottom: 1px solid #fb923c;
}
.offline-banner .material-symbols-rounded {
	font-size: 18px;
}
.fade-enter-active,
.fade-leave-active {
	transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
	opacity: 0;
}
</style>
