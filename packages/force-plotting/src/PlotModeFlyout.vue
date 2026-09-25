<script setup lang="ts">
// Collapsed plot-mode picker: shows only the ACTIVE mode until pointed at, then slides the rest
// out beside it. Both the Record page's ForcePanel and the Plot dashboard's Signals panel use it,
// so the two toolbars stay identical.
//
// Every option is always in the DOM (just clipped) rather than rendered on open, for two reasons:
// the slide can animate from a real measured width, and `listEl.scrollWidth` reports the full
// natural width even while collapsed -- which is how the horizontal-vs-vertical decision below is
// made without a hidden measuring pass.
import { computed, ref } from 'vue';

const props = defineProps<{
	modes: { key: string; label: string; title?: string }[];
	modelValue: string;
}>();
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>();

const open = ref(false);
const vertical = ref(false);
const rootEl = ref<HTMLElement | null>(null);
const listEl = ref<HTMLElement | null>(null);

const active = computed(() => props.modes.find((m) => m.key === props.modelValue) ?? props.modes[0]);
const others = computed(() => props.modes.filter((m) => m.key !== active.value?.key));

// Decided per-open, not once on mount: these toolbars wrap and reflow (the panel is resizable and
// the grid is user-arranged), so the space beside this control is not a fixed property of it.
// The horizontal list only ever opens to the RIGHT, inside the host toolbar, so the room that
// matters is between this control and the toolbar's (or viewport's) right edge.
function reflow() {
	const root = rootEl.value, list = listEl.value;
	if (!root || !list) return;
	const r = root.getBoundingClientRect();
	const edge = Math.min(window.innerWidth, root.parentElement?.getBoundingClientRect().right ?? window.innerWidth);
	const needed = list.scrollWidth + 8;
	vertical.value = needed > edge - r.right - 4;
}
function show() { if (!open.value) reflow(); open.value = true; }
function hide() { open.value = false; }
function pick(key: string) {
	emit('update:modelValue', key);
	open.value = false;
}
// Hover-to-open is for mice only: touch fires emulated enter/leave around every tap.
function onEnter(ev: PointerEvent) { if (ev.pointerType === 'mouse') show(); }
function onLeave(ev: PointerEvent) { if (ev.pointerType === 'mouse') hide(); }
// A tap focuses the button (focusin -> show) before its click lands, so toggling on the click's
// view of `open` would immediately close what the tap just opened. Toggle on the state at press.
let openAtPress: boolean | null = null;
function onActivePress() { openAtPress = open.value; }
function onActiveClick() {
	const wasOpen = openAtPress ?? open.value;
	openAtPress = null;
	if (wasOpen) hide(); else show();
}
</script>

<template>
	<div ref="rootEl" class="pmf" :class="{ open, vertical }"
		@pointerenter="onEnter" @pointerleave="onLeave" @focusin="show" @focusout="hide">
		<!-- data-mode is the stable hook for "select mode X": the visible label differs between
			 hosts ("Force" vs "Time") and the active button carries a caret, so matching on text is
			 unreliable. -->
		<button type="button" class="pmf-btn pmf-active" :data-mode="active?.key"
			:title="active?.title || active?.label" @pointerdown="onActivePress" @click="onActiveClick">
			{{ active?.label }}
			<span class="pmf-caret" aria-hidden="true">›</span>
		</button>
		<div ref="listEl" class="pmf-list">
			<button v-for="m in others" :key="m.key" type="button" class="pmf-btn" :data-mode="m.key"
				:title="m.title || m.label" :tabindex="open ? 0 : -1" @click="pick(m.key)">{{ m.label }}</button>
		</div>
	</div>
</template>

<style scoped>
.pmf { position: relative; display: inline-flex; align-items: center; }
.pmf-btn {
	padding: 5px 10px; font: inherit; font-size: 12px; line-height: 1.2; white-space: nowrap;
	color: var(--text-dim, var(--theme--foreground-subdued, #6b7684)); background: var(--surface, var(--theme--background-subdued, #f7f9fb));
	border: 1px solid var(--border, var(--theme--border-color-subdued, #e7ebf0)); border-radius: 7px; cursor: pointer;
}
.pmf-btn:hover { color: var(--text, var(--theme--foreground, #1e293b)); background: var(--surface-2, var(--theme--background-normal, #f0f4f9)); }
.pmf-active { display: inline-flex; align-items: center; gap: 5px; background: var(--accent, var(--theme--primary, #1d4ed8)); color: var(--accent-ink, var(--theme--foreground-inverted, #fff)); font-weight: 600; border-color: var(--accent, var(--theme--primary, #1d4ed8)); }
.pmf-caret { font-size: 13px; line-height: 1; transition: transform 0.24s ease; opacity: 0.85; }
.pmf.open .pmf-caret { transform: rotate(90deg); }

/* Horizontal (default): max-width carries the slide, so it animates without hardcoding a width. */
.pmf-list {
	display: flex; gap: 4px; overflow: hidden;
	max-width: 0; opacity: 0; margin-left: 0;
	transition: max-width 0.28s ease, opacity 0.18s ease, margin-left 0.28s ease;
}
.pmf.open .pmf-list { max-width: 620px; opacity: 1; margin-left: 4px; }

/* Vertical fallback when the row can't fit the full list beside the active button. */
.pmf.vertical .pmf-list {
	position: absolute; top: calc(100% + 4px); left: 0; z-index: 40;
	flex-direction: column; max-width: none; margin-left: 0;
	max-height: 0; padding: 0;
	background: var(--bg-2, var(--theme--background, #fff)); border: 1px solid transparent; border-radius: 9px;
	transition: max-height 0.28s ease, opacity 0.18s ease, padding 0.2s ease;
}
.pmf.vertical.open .pmf-list {
	max-height: 320px; padding: 4px; border-color: var(--border, var(--theme--border-color-subdued, #e7ebf0));
	box-shadow: 0 12px 34px rgba(0, 0, 0, 0.3);
}
.pmf.vertical .pmf-btn { text-align: left; width: 100%; }

@media (prefers-reduced-motion: reduce) {
	.pmf-list, .pmf-caret { transition: none; }
}
</style>
