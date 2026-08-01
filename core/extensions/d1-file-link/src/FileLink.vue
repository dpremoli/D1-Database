<template>
	<div class="d1-file-link">
		<v-input
			:model-value="value"
			placeholder="\\\\server\\share\\path\\file.mat"
			@update:model-value="emit('input', $event)"
		>
			<template #append>
				<v-icon
					v-tooltip="copied ? 'Copied!' : 'Copy path'"
					:name="copied ? 'check' : 'content_copy'"
					clickable
					@click="copy"
				/>
				<a v-if="fileUri" :href="fileUri" target="_blank" rel="noopener" class="open">
					<v-icon v-tooltip="'Open (may be blocked by the browser)'" name="open_in_new" clickable />
				</a>
			</template>
		</v-input>
	</div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';

const props = defineProps<{ value: string | null }>();
const emit = defineEmits<{ (e: 'input', value: string | null): void }>();

const copied = ref(false);

// Z:\a\b file.mat  ->  file:///Z:/a/b%20file.mat
const fileUri = computed(() => {
	if (!props.value) return '';
	return 'file:///' + encodeURI(props.value.replace(/\\/g, '/'));
});

async function copy() {
	if (!props.value) return;
	try {
		await navigator.clipboard.writeText(props.value);
	} catch {
		// fallback for non-secure contexts
		const ta = document.createElement('textarea');
		ta.value = props.value;
		document.body.appendChild(ta);
		ta.select();
		document.execCommand('copy');
		document.body.removeChild(ta);
	}
	copied.value = true;
	setTimeout(() => (copied.value = false), 1500);
}
</script>

<style scoped>
.d1-file-link { width: 100%; }
.open { display: inline-flex; align-items: center; }
</style>
