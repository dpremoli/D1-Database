<script setup lang="ts">
// A titled panel shell for the modular recording workspace. The header doubles as the grid
// drag handle (class `panel-handle`, referenced by GridItem's drag-allow-from). Emits `close`
// when the ✕ is clicked so the workspace can remove this panel instance.
defineProps<{ title: string; icon?: string; closable?: boolean }>();
defineEmits<{ close: [] }>();
</script>

<template>
	<div class="panel-frame">
		<div class="panel-handle">
			<span v-if="icon" class="material-symbols-rounded">{{ icon }}</span>
			<span class="panel-title">{{ title }}</span>
			<span class="panel-grip material-symbols-rounded">drag_indicator</span>
			<button v-if="closable" class="panel-close" title="Close panel" @pointerdown.stop @click.stop="$emit('close')">
				<span class="material-symbols-rounded">close</span>
			</button>
		</div>
		<div class="panel-body"><slot /></div>
	</div>
</template>

<style scoped>
.panel-frame { display: flex; flex-direction: column; height: 100%; background: rgba(17,26,51,0.62); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
.panel-handle { display: flex; align-items: center; gap: 7px; padding: 8px 12px; cursor: move; background: rgba(255,255,255,0.03); border-bottom: 1px solid var(--border); user-select: none; }
.panel-handle .material-symbols-rounded { font-size: 17px; color: var(--text-dim); }
.panel-title { font-size: 12.5px; font-weight: 640; letter-spacing: 0.01em; }
.panel-grip { margin-left: auto; opacity: 0.5; }
.panel-close { display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; padding: 0; border: none; background: transparent; color: var(--text-dim); cursor: pointer; border-radius: 5px; }
.panel-close:hover { color: var(--danger); background: rgba(239,68,68,0.12); }
.panel-close .material-symbols-rounded { font-size: 15px; }
.panel-body { flex: 1; min-height: 0; overflow: auto; padding: 12px; }
</style>
