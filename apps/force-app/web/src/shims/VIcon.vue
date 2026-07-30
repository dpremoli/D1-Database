<script setup lang="ts">
// Minimal stand-in for Directus's global <v-icon>. Renders a Material Symbols glyph by name.
// Only the props the ported components actually use are supported.
import { computed } from 'vue';

const props = defineProps<{
	name?: string;
	small?: boolean;
	xSmall?: boolean;
	large?: boolean;
	xLarge?: boolean;
	left?: boolean;
	right?: boolean;
}>();

const sizePx = computed(() => {
	if (props.xSmall) return 14;
	if (props.small) return 18;
	if (props.large) return 32;
	if (props.xLarge) return 40;
	return 24;
});
</script>

<template>
	<span
		class="material-symbols-rounded v-icon-shim"
		:style="{ fontSize: sizePx + 'px', marginRight: right ? '4px' : undefined, marginLeft: left ? '4px' : undefined }"
		aria-hidden="true"
		>{{ name }}</span
	>
</template>

<style scoped>
.v-icon-shim {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	line-height: 1;
	vertical-align: middle;
	user-select: none;
	font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24;
}
</style>
