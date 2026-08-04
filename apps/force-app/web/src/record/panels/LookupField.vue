<script setup lang="ts">
// Debounced Directus typeahead. Emits the selected id (v-model) and a `select` event with the full
// item (for auto-fill, e.g. sample diameter). Shows the chosen label; a clear button resets it.
import { ref, watch } from 'vue';
import type { LookupItem } from '../directusLookups';

const props = defineProps<{
	modelValue: string;
	label: string;
	search: (q: string) => Promise<LookupItem[]>;
	placeholder?: string;
	disabled?: boolean;
	displayLabel?: string;
}>();
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void; (e: 'select', item: LookupItem): void }>();

const text = ref(props.displayLabel || '');
const open = ref(false);
const items = ref<LookupItem[]>([]);
const loading = ref(false);
const inputEl = ref<HTMLInputElement | null>(null);
let t: any = null;

watch(() => props.displayLabel, (v) => { if (v !== undefined) text.value = v; });

function onInput() {
	emit('update:modelValue', ''); // typing invalidates the current selection
	open.value = true;
	clearTimeout(t);
	t = setTimeout(runSearch, 250);
}
async function runSearch() {
	loading.value = true;
	try { items.value = await props.search(text.value); } catch { items.value = []; } finally { loading.value = false; }
}
function focus() { open.value = true; if (items.value.length === 0) runSearch(); }
function pick(it: LookupItem) {
	emit('update:modelValue', it.id);
	emit('select', it);
	text.value = it.label;
	close();
}
// Close and drop focus so the menu can't linger/re-open after a pick or Escape.
function close() { open.value = false; inputEl.value?.blur(); }
function clear() { emit('update:modelValue', ''); text.value = ''; items.value = []; }
</script>

<template>
	<label class="lookup">
		<span class="lbl">{{ label }}</span>
		<div class="box" :class="{ set: !!modelValue }">
			<input ref="inputEl" v-model="text" :placeholder="placeholder" :disabled="disabled"
				@input="onInput" @focus="focus" @keydown.esc.prevent="close" @keydown.enter.prevent="items[0] && pick(items[0])"
				@blur="() => setTimeout(() => (open = false), 150)" />
			<button v-if="modelValue" class="x" type="button" :disabled="disabled" @mousedown.prevent="clear">
				<span class="material-symbols-rounded">close</span>
			</button>
		</div>
		<div v-if="open && !disabled" class="menu">
			<div v-if="loading" class="mi hint">searching…</div>
			<button v-for="it in items" :key="it.id" type="button" class="mi" @mousedown.prevent="pick(it)">
				<span class="mi-label">{{ it.label }}</span>
				<span v-if="it.sublabel" class="mi-sub">{{ it.sublabel }}</span>
			</button>
			<div v-if="!loading && items.length === 0" class="mi hint">no matches</div>
		</div>
	</label>
</template>

<style scoped>
.lookup { display: block; position: relative; margin-bottom: 8px; }
.lbl { display: block; font-size: 11.5px; color: var(--text-dim); margin-bottom: 3px; }
.box { display: flex; align-items: center; background: rgba(0,0,0,0.25); border: 1px solid var(--border); border-radius: 7px; }
.box.set { border-color: rgba(56,189,248,0.5); }
.box input { flex: 1; padding: 7px 9px; font-size: 13px; color: var(--text); background: transparent; border: none; outline: none; }
.box input:disabled { opacity: 0.55; }
.x { display: inline-flex; align-items: center; padding: 0 6px; background: transparent; border: none; color: var(--text-dim); cursor: pointer; }
.x .material-symbols-rounded { font-size: 15px; }
.menu { position: absolute; z-index: 30; left: 0; right: 0; top: 100%; margin-top: 2px; max-height: 200px; overflow: auto; background: #0e162c; border: 1px solid var(--border); border-radius: 8px; box-shadow: 0 12px 30px rgba(0,0,0,0.45); }
.mi { display: block; width: 100%; text-align: left; padding: 7px 10px; font-size: 12.5px; font-family: var(--mono); color: var(--text); background: transparent; border: none; cursor: pointer; }
.mi:hover { background: var(--surface); }
.mi.hint { color: var(--text-dim); font-family: inherit; cursor: default; }
.mi-label { display: block; }
.mi-sub { display: block; margin-top: 1px; font-family: inherit; font-size: 11px; color: var(--text-dim); }
</style>
