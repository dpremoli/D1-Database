<script setup lang="ts">
// Single app-wide host for confirmAction() — mounted once in App.vue so every route (including
// the login page) can prompt without each page owning dialog markup. See ui/confirm.ts for why
// this exists rather than window.confirm().
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { confirmState, resolveActive } from './confirm';

const cancelBtn = ref<HTMLButtonElement | null>(null);
const confirmBtn = ref<HTMLButtonElement | null>(null);
const panel = ref<HTMLElement | null>(null);

function cancel() { resolveActive(false); }
function accept() { resolveActive(true); }

// Focus lands on Cancel for destructive prompts and Confirm for benign ones: a stray Enter or
// Space on a "disable the high-force alarm" prompt must not arm the dangerous outcome, but making
// every routine confirmation need a deliberate Tab is friction for no safety gain.
watch(
	() => confirmState.current,
	async (cur) => {
		if (!cur) return;
		await nextTick();
		const danger = cur.tone === 'danger' || cur.tone === 'warning';
		(danger ? cancelBtn.value : confirmBtn.value)?.focus();
	},
	{ immediate: true },
);

function onKeydown(e: KeyboardEvent) {
	if (!confirmState.current) return;
	if (e.key === 'Escape') { e.preventDefault(); cancel(); return; }
	// Keep focus inside the dialog: it is modal, so tabbing to the page behind it would let the
	// operator interact with controls the prompt is meant to be blocking.
	if (e.key === 'Tab' && panel.value) {
		const els = panel.value.querySelectorAll<HTMLElement>('button');
		if (!els.length) return;
		const first = els[0];
		const last = els[els.length - 1];
		if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
		else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
	}
}
onMounted(() => window.addEventListener('keydown', onKeydown, true));
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown, true));
</script>

<template>
	<transition name="cd-fade">
		<div
			v-if="confirmState.current"
			class="cd-backdrop"
			data-testid="confirm-dialog"
			@click.self="cancel"
		>
			<div
				ref="panel"
				class="cd-modal"
				:class="confirmState.current.tone ?? 'default'"
				role="alertdialog"
				aria-modal="true"
				aria-labelledby="cd-title"
				aria-describedby="cd-message"
			>
				<header class="cd-head">
					<span class="material-symbols-rounded cd-icon">
						{{ confirmState.current.tone === 'danger' ? 'warning'
							: confirmState.current.tone === 'warning' ? 'error' : 'help' }}
					</span>
					<b id="cd-title">{{ confirmState.current.title }}</b>
				</header>

				<p id="cd-message" class="cd-message">{{ confirmState.current.message }}</p>
				<p v-if="confirmState.current.detail" class="cd-detail">{{ confirmState.current.detail }}</p>

				<dl v-if="confirmState.current.stats?.length" class="cd-stats">
					<div v-for="s in confirmState.current.stats" :key="s.label" class="cd-stat">
						<dt>{{ s.label }}</dt>
						<dd>{{ s.value }}</dd>
					</div>
				</dl>

				<div class="cd-actions">
					<button ref="cancelBtn" class="cd-btn" data-testid="confirm-cancel" @click="cancel">
						{{ confirmState.current.cancelLabel ?? 'Cancel' }}
					</button>
					<div class="cd-spacer"></div>
					<button
						ref="confirmBtn"
						class="cd-btn"
						:class="confirmState.current.tone === 'danger' ? 'danger' : 'primary'"
						data-testid="confirm-accept"
						@click="accept"
					>
						{{ confirmState.current.confirmLabel ?? 'Confirm' }}
					</button>
				</div>
			</div>
		</div>
	</transition>
</template>

<style scoped>
/* z-index sits above .alarm-overlay (100) and .rec-banner (150) — the alarm banner is precisely
   what one of these prompts is launched from, so the dialog must not appear behind it. */
.cd-backdrop { position: fixed; inset: 0; z-index: 300; display: flex; align-items: center; justify-content: center; padding: 24px; background: rgba(0,0,0,0.55); backdrop-filter: blur(2px); }
.cd-modal { width: min(440px, 100%); display: flex; flex-direction: column; gap: 12px; padding: 20px; background: var(--bg-2); border: 1px solid var(--border); border-radius: 14px; box-shadow: 0 30px 80px rgba(0,0,0,0.45); }
.cd-head { display: flex; align-items: center; gap: 10px; }
.cd-head b { font-size: 15px; color: var(--text); }
.cd-icon { font-size: 24px; color: var(--accent); }
.cd-modal.danger .cd-icon { color: #ef4444; }
.cd-modal.warning .cd-icon { color: #fbbf24; }
.cd-message { margin: 0; font-size: 13.5px; line-height: 1.55; color: var(--text); }
.cd-detail { margin: 0; font-size: 12px; line-height: 1.5; color: var(--text-dim); }
.cd-stats { display: flex; flex-direction: column; gap: 4px; margin: 0; padding: 10px 12px; background: var(--surface); border: 1px solid var(--border); border-radius: 9px; }
.cd-stat { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.cd-stat dt { font-size: 12px; color: var(--text-dim); }
.cd-stat dd { margin: 0; font-size: 12.5px; font-weight: 600; color: var(--text); font-variant-numeric: tabular-nums; }
.cd-actions { display: flex; align-items: center; gap: 10px; margin-top: 2px; }
.cd-spacer { flex: 1; }
.cd-btn { padding: 9px 16px; font-size: 13px; font-weight: 600; color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: 9px; cursor: pointer; }
.cd-btn:hover { background: var(--surface-2); }
.cd-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.cd-btn.primary { color: var(--accent-ink); background: var(--accent); border-color: var(--accent); }
.cd-btn.danger { color: #fff; background: #dc2626; border-color: #dc2626; }
.cd-fade-enter-active, .cd-fade-leave-active { transition: opacity 0.12s ease; }
.cd-fade-enter-from, .cd-fade-leave-to { opacity: 0; }
</style>
