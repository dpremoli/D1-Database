<script setup lang="ts">
// The recipe column of the Diagnostics Workbench: an editable step list. The panel never calls
// diag-service — it edits the recipe object (v-model) and shows preview/bake status the
// workbench passes down. Phase D-1 was on/off + param tuning; Phase F adds add/remove step,
// the seed-layer binding for grow_segmentation, and the recipe library.
import { computed } from 'vue';
import { STEP_META, type Recipe, type RecipeStep } from './recipeChannels';
import RecipeLibrary from './RecipeLibrary.vue';
import type { SavedRecipe } from './diagRecipes';

const props = defineProps<{
	recipe: Recipe;
	baked: boolean;
	bakeStale: boolean;
	previewing: boolean;
	previewMs: number | null;
	previewError: string | null;
	seedLayerNames: string[];
	library: SavedRecipe[];
	collapsed?: boolean;
}>();
const emit = defineEmits<{
	(e: 'update:recipe', r: Recipe): void;
	(e: 'update:collapsed', v: boolean): void;
	(e: 'bake'): void;
	(e: 'apply', r: Recipe): void;
	(e: 'library-changed'): void;
	(e: 'run-step', op: 'getis_ord' | 'hdbscan' | 'grow_segmentation'): void;
}>();

// s1..s7 are the built-in default steps — not removable. Anything added carries an x-prefixed id.
const DEFAULT_IDS = new Set(['s1', 's2', 's3', 's4', 's5', 's6', 's7']);

// Steps whose statistics run on the FRAMED viewport at full resolution (Phase G), not on the
// 256/rev bake. Gi* auto-fires on pan/zoom settle; HDBSCAN / segmentation run on the button.
const SPATIAL_OPS = new Set(['getis_ord', 'hdbscan', 'grow_segmentation']);
const BUTTON_OPS = new Set(['hdbscan', 'grow_segmentation']);

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
		s.params[key] = spec?.kind === 'number' ? (raw === '' ? null : Number(raw)) : raw;
	});
}

const addableOps = computed(() => {
	const present = new Set(props.recipe.steps.map((s) => s.op));
	return Object.keys(STEP_META).filter((op) => !present.has(op));
});

function defaultParams(op: string): Record<string, number | string | null> {
	const out: Record<string, number | string | null> = {};
	for (const p of STEP_META[op]?.params ?? []) {
		out[p.key] = p.kind === 'number' ? (p.min ?? 0) : (p.options?.[0]?.value ?? '');
	}
	return out;
}
function addStep(op: string) {
	if (!op) return;
	edit((r) => {
		const step: RecipeStep = { id: `x${Date.now()}`, op, on: true, params: defaultParams(op) };
		if (op === 'grow_segmentation') step.inputs = { seeds: { layers: [], required: false } };
		r.steps.push(step);
	});
}
function removeStep(id: string) {
	edit((r) => { r.steps = r.steps.filter((s) => s.id !== id); });
}

function seedBound(s: RecipeStep): string[] {
	return ((s.inputs?.seeds as { layers?: string[] } | undefined)?.layers) ?? [];
}
function toggleSeed(id: string, name: string) {
	edit((r) => {
		const s = r.steps.find((x) => x.id === id);
		if (!s) return;
		s.inputs = s.inputs ?? {};
		const seeds = (s.inputs.seeds as { layers: string[]; required: boolean } | undefined)
			?? { layers: [], required: false };
		seeds.layers = seeds.layers.includes(name)
			? seeds.layers.filter((n) => n !== name)
			: [...seeds.layers, name];
		s.inputs.seeds = seeds;
	});
}
</script>

<template>
	<div class="recipe-panel">
		<button class="rp-collapse" @click="emit('update:collapsed', !collapsed)">
			<span>{{ collapsed ? '▸' : '▾' }}</span>
			<span>{{ collapsed ? 'Recipe (collapsed)' : 'Recipe steps' }}</span>
		</button>
		<ol v-show="!collapsed" class="steps">
			<li v-for="s in recipe.steps" :key="s.id" :class="{ off: !s.on }">
				<label class="step-head">
					<input type="checkbox" :checked="s.on" @change="toggle(s.id)" />
					<span class="step-label">{{ STEP_META[s.op]?.label ?? s.op }}</span>
					<span class="tier" :class="STEP_META[s.op]?.tier">{{ STEP_META[s.op]?.tier }}</span>
					<button v-if="!DEFAULT_IDS.has(s.id)" class="rm" title="remove step" @click.prevent="removeStep(s.id)">✕</button>
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
				<div v-if="s.on && SPATIAL_OPS.has(s.op)" class="scope-note">
					<span>runs on the current view · full resolution</span>
					<button v-if="BUTTON_OPS.has(s.op)" class="run-step-btn"
						@click.prevent="emit('run-step', s.op as 'hdbscan' | 'grow_segmentation')">
						Run on this view
					</button>
				</div>
				<div v-if="s.on && s.op === 'grow_segmentation'" class="seed-bind">
					<span class="seed-title">Seed classes</span>
					<p v-if="!seedLayerNames.length" class="seed-hint">paint a seed layer first</p>
					<label v-for="name in seedLayerNames" :key="name" class="seed-row">
						<input type="checkbox" :checked="seedBound(s).includes(name)" @change="toggleSeed(s.id, name)" />
						<span>{{ name }}</span>
						<span v-if="seedBound(s).includes(name)" class="seed-idx">class {{ seedBound(s).indexOf(name) }}</span>
					</label>
				</div>
			</li>
		</ol>

		<div class="add-step" v-if="!collapsed && addableOps.length">
			<select @change="addStep(($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).value = ''">
				<option value="">+ add step…</option>
				<option v-for="op in addableOps" :key="op" :value="op">{{ STEP_META[op].label }}</option>
			</select>
		</div>

		<div class="rp-footer">
			<RecipeLibrary
				:library="library"
				:current-recipe="recipe"
				@apply="(r) => emit('apply', r)"
				@saved="emit('library-changed')"
				@deleted="emit('library-changed')"
			/>
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
.rm { border: none; background: none; color: var(--text-dim, #94a3b8); cursor: pointer; font-size: 11px; }
.params { display: grid; grid-template-columns: 1fr 1fr; gap: 5px 8px; margin-top: 6px; padding-left: 22px; }
.param { display: flex; flex-direction: column; gap: 2px; }
.param span { font-size: 10px; color: var(--text-dim, #94a3b8); }
.param input, .param select {
	font: inherit; font-size: 11px; padding: 3px 5px; background: var(--bg-2, #111a33);
	color: var(--text, #e5e7eb); border: 1px solid var(--border, rgba(255,255,255,0.14)); border-radius: 5px;
}
.seed-bind { margin-top: 6px; padding-left: 22px; display: flex; flex-direction: column; gap: 3px; }
.seed-title { font-size: 10px; color: var(--text-dim, #94a3b8); }
.seed-hint { margin: 0; font-size: 10px; font-style: italic; color: var(--text-dim, #94a3b8); }
.seed-row { display: flex; align-items: center; gap: 6px; font-size: 11px; }
.seed-idx { font-size: 9px; color: var(--text-dim, #94a3b8); }
.rp-collapse { display: flex; align-items: center; gap: 6px; width: 100%; font: inherit; font-size: 11px; font-weight: 600; color: var(--text-dim, #94a3b8); background: none; border: none; border-bottom: 1px solid var(--border, rgba(255,255,255,0.08)); padding: 6px 10px; cursor: pointer; text-align: left; }
.scope-note { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 6px; padding-left: 22px; font-size: 10px; color: #86efac; }
.run-step-btn { font: inherit; font-size: 10px; cursor: pointer; padding: 2px 7px; border-radius: 5px; color: var(--text, #e5e7eb); background: var(--bg-2, #111a33); border: 1px solid var(--border, rgba(255,255,255,0.18)); }
.add-step { padding: 6px 10px; border-bottom: 1px solid var(--border, rgba(255,255,255,0.08)); }
.add-step select { width: 100%; font-size: 11px; padding: 3px 5px; background: var(--bg-2, #111a33); color: var(--text, #e5e7eb); border: 1px solid var(--border, rgba(255,255,255,0.14)); border-radius: 5px; }
.rp-footer { flex-shrink: 0; border-top: 1px solid var(--border, rgba(255,255,255,0.12)); padding: 8px 10px; display: flex; flex-direction: column; gap: 6px; }
.preview-line { font-size: 11px; color: var(--text-dim, #94a3b8); font-style: italic; min-height: 14px; }
.preview-line .err { color: var(--danger, #fca5a5); font-style: normal; }
.bake-btn {
	font: inherit; font-size: 12px; font-weight: 650; cursor: pointer; padding: 6px 12px; border-radius: 7px;
	color: var(--accent-ink, #0b1020); background: var(--accent, #38bdf8); border: 1px solid var(--accent, #38bdf8);
}
.bake-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
