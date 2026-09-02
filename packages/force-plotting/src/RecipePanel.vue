<script setup lang="ts">
// The recipe column of the Diagnostics Workbench: an editable step list. The panel never
// calls diag-service — it edits the recipe object (v-model) and shows preview/bake status the
// workbench passes down. Step reorder / add / remove are Phase F (recipe library); D-1 is
// on/off toggles and parameter tuning only.
import { STEP_META, type Recipe } from './recipeChannels';

const props = defineProps<{
	recipe: Recipe;
	baked: boolean;
	bakeStale: boolean;
	previewing: boolean;
	previewMs: number | null;
	previewError: string | null;
}>();
const emit = defineEmits<{
	(e: 'update:recipe', r: Recipe): void;
	(e: 'bake'): void;
}>();

function edit(mut: (r: Recipe) => void) {
	const next = JSON.parse(JSON.stringify(props.recipe)) as Recipe;
	mut(next);
	emit('update:recipe', next);
}

function toggle(id: string) {
	edit((r) => {
		const s = r.steps.find((x) => x.id === id);
		if (s) s.on = !s.on;
	});
}

function setParam(id: string, key: string, raw: string) {
	edit((r) => {
		const s = r.steps.find((x) => x.id === id);
		if (!s) return;
		const spec = STEP_META[s.op]?.params.find((p) => p.key === key);
		if (spec?.kind === 'number') {
			s.params[key] = raw === '' ? null : Number(raw);
		} else {
			s.params[key] = raw;
		}
	});
}
</script>

<template>
	<div class="recipe-panel">
		<ol class="steps">
			<li v-for="s in recipe.steps" :key="s.id" :class="{ off: !s.on }">
				<label class="step-head">
					<input type="checkbox" :checked="s.on" @change="toggle(s.id)" />
					<span class="step-label">{{ STEP_META[s.op]?.label ?? s.op }}</span>
					<span class="tier" :class="STEP_META[s.op]?.tier">{{ STEP_META[s.op]?.tier }}</span>
				</label>
				<div v-if="s.on && STEP_META[s.op]?.params.length" class="params">
					<label v-for="p in STEP_META[s.op].params" :key="p.key" class="param">
						<span>{{ p.label }}</span>
						<select v-if="p.kind === 'select'"
							:value="String(s.params[p.key] ?? '')"
							@change="setParam(s.id, p.key, ($event.target as HTMLSelectElement).value)">
							<option v-for="o in p.options" :key="o.value" :value="o.value">{{ o.label }}</option>
						</select>
						<input v-else type="number"
							:value="s.params[p.key] ?? ''"
							:min="p.min" :max="p.max" :step="p.step"
							@change="setParam(s.id, p.key, ($event.target as HTMLInputElement).value)" />
					</label>
				</div>
			</li>
		</ol>

		<div class="rp-footer">
			<div class="preview-line">
				<span v-if="previewing">previewing…</span>
				<span v-else-if="previewError" class="err">{{ previewError }}</span>
				<span v-else-if="previewMs != null">previewed in {{ previewMs }} ms · approximate</span>
				<span v-else-if="baked">showing last bake</span>
			</div>
			<button class="bake-btn" :disabled="previewing" @click="emit('bake')">
				{{ bakeStale ? 'Bake (recipe changed)' : 'Re-bake' }}
			</button>
		</div>
	</div>
</template>

<style scoped>
.recipe-panel { display: flex; flex-direction: column; height: 100%; min-height: 0; font-size: 12px; }
.steps { list-style: none; margin: 0; padding: 0; overflow-y: auto; flex: 1; }
.steps li { border-bottom: 1px solid var(--border, rgba(255,255,255,0.08)); padding: 6px 10px; }
.steps li.off { opacity: 0.5; }
.step-head { display: flex; align-items: center; gap: 7px; cursor: pointer; }
.step-label { font-weight: 600; flex: 1; }
.tier { font-size: 9px; text-transform: uppercase; letter-spacing: 0.04em; padding: 1px 5px; border-radius: 4px; }
.tier.base { background: color-mix(in srgb, #d97706 22%, transparent); color: #fcd34d; }
.tier.derived { background: color-mix(in srgb, #16a34a 22%, transparent); color: #86efac; }
.params { display: grid; grid-template-columns: 1fr 1fr; gap: 5px 8px; margin-top: 6px; padding-left: 22px; }
.param { display: flex; flex-direction: column; gap: 2px; }
.param span { font-size: 10px; color: var(--text-dim, #94a3b8); }
.param input, .param select {
	font: inherit; font-size: 11px; padding: 3px 5px; background: var(--bg-2, #111a33);
	color: var(--text, #e5e7eb); border: 1px solid var(--border, rgba(255,255,255,0.14)); border-radius: 5px;
}
.rp-footer { flex-shrink: 0; border-top: 1px solid var(--border, rgba(255,255,255,0.12)); padding: 8px 10px; display: flex; flex-direction: column; gap: 6px; }
.preview-line { font-size: 11px; color: var(--text-dim, #94a3b8); font-style: italic; min-height: 14px; }
.preview-line .err { color: var(--danger, #fca5a5); font-style: normal; }
.bake-btn {
	font: inherit; font-size: 12px; font-weight: 650; cursor: pointer; padding: 6px 12px; border-radius: 7px;
	color: var(--accent-ink, #0b1020); background: var(--accent, #38bdf8); border: 1px solid var(--accent, #38bdf8);
}
.bake-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
