<script setup lang="ts">
import { computed } from 'vue';
import { collectionRoute, dataStudioRoute } from '@d1/ui';

// Stands in for an Explorer page that is not built yet, so a link to it never 404s: it says so and
// offers the Data Studio form (or list) instead.
const props = defineProps<{ collection: string; title: string; id?: string }>();

const studioTo = computed(() => (props.id ? dataStudioRoute(props.collection, props.id) : `/content/${props.collection}`));
// The Explorer index for a collection, when it has one, is the page we are standing in.
const isIndex = computed(() => !props.id && collectionRoute(props.collection).startsWith('/home'));
</script>

<template>
	<private-view :title="title">
		<div class="placeholder">
			<v-icon name="construction" large />
			<h2>This page is not built yet</h2>
			<p v-if="isIndex">The {{ title.toLowerCase() }} overview is coming. Until then, use the Data Studio list.</p>
			<p v-else>This record does not have its own page yet. Until then, open it in the Data Studio.</p>
			<div class="buttons">
				<v-button :to="studioTo">Open in Data Studio</v-button>
				<v-button secondary to="/home">Back to Home</v-button>
			</div>
		</div>
	</private-view>
</template>

<style scoped>
.placeholder {
	max-width: 560px;
	margin: 64px auto;
	padding: 0 32px;
	text-align: center;
	display: flex;
	flex-direction: column;
	align-items: center;
	gap: 10px;
	color: var(--theme--foreground);
}
.placeholder :deep(.v-icon) { --v-icon-color: var(--theme--foreground-subdued); }
h2 { margin: 6px 0 0; font-size: 20px; }
p { margin: 0; color: var(--theme--foreground-subdued); }
.buttons { display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; justify-content: center; }
</style>
