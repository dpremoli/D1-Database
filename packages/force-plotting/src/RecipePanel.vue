<script setup lang="ts">
// The recipe column of the Diagnostics Workbench: the processing pipeline as an editable
// program, in the shape a recipe-driven analysis tool (MIPAR and friends) uses — numbered
// steps, each owning its own parameters, scope and run control, with one commit action at
// the bottom.
//
// Three things this panel exists to make legible, all of which were previously invisible:
//   1. WHERE a step's result comes from. A recipe mixes steps that only run during a host
//      Bake (base tier, full-rate input), steps that re-run live over the whole cut, and
//      spatial steps that ALSO re-run on the framed viewport at full resolution. Same list,
//      three different costs and three different answers — so every step wears its scope.
//   2. WHETHER the recipe can run at all. Toggling a step off can strand a later one; the
//      service answers that with a 422 and a Python error string. recipeProblems() catches it
//      here, marks the step, and names the fix in step labels.
//   3. WHAT each knob does. Every step and every parameter carries prose from diagHelp.ts.
//      'Min cluster' read as "number of clusters" and cost an analyst a debugging session; it
//      is a floor measured in grid cells, and now says so.
import { computed, ref } from 'vue';
import {
	CATEGORY_LABELS, CATEGORY_ORDER, STEP_META,
	type Recipe, type RecipeProblem, type RecipeStep, type StepCategory,
} from './recipeChannels';
import type { ViewportOp } from './diagViewport';
import { ACTION_HELP, PANEL_HELP, SCOPE_META, STEP_HELP, scopeOf } from './diagHelp';
import RecipeLibrary from './RecipeLibrary.vue';
import InfoTip from './InfoTip.vue';
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
	/** Steps that cannot run as configured — from recipeProblems(). */
	problems?: RecipeProblem[];
	/** op currently running on the viewport, so its button can show progress. */
	busyOp?: string | null;
	/** true while a host bake is queued or running. */
	baking?: boolean;
	/** ops the preview silently skipped (base-tier steps), from X-Diag-Skipped. */
	skippedOps?: string[];
}>();
const emit = defineEmits<{
	(e: 'update:recipe', r: Recipe): void;
	(e: 'update:collapsed', v: boolean): void;
	(e: 'bake'): void;
	(e: 'apply', r: Recipe): void;
	(e: 'library-changed'): void;
	(e: 'run-step', op: ViewportOp): void;
}>();

// s1..s7 are the built-in default steps — not removable. Anything added carries an x-prefixed id.
const DEFAULT_IDS = new Set(['s1', 's2', 's3', 's4', 's5', 's6', 's7']);

const problemFor = computed(() => {
	const m = new Map<string, RecipeProblem>();
	for (const p of props.problems ?? []) m.set(p.stepId, p);
	return m;
});
const skipped = computed(() => new Set(props.skippedOps ?? []));

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

// Grouped by category so the picker reads as "what kind of thing do I want to add" rather
// than a flat alphabetical dump. CATEGORY_ORDER, not object insertion order, so the groups
// appear in a stable, roughly-pipeline sequence regardless of STEP_META's own key order.
const addableByCategory = computed(() => {
	const byCat = new Map<StepCategory, string[]>();
	for (const op of addableOps.value) {
		const cat = STEP_META[op].category;
		(byCat.get(cat) ?? byCat.set(cat, []).get(cat)!).push(op);
	}
	return CATEGORY_ORDER
		.map((cat) => ({ cat, label: CATEGORY_LABELS[cat], ops: byCat.get(cat) ?? [] }))
		.filter((g) => g.ops.length > 0);
});

function defaultParams(op: string): Record<string, number | string | null> {
	const out: Record<string, number | string | null> = {};
	for (const p of STEP_META[op]?.params ?? []) {
		// p.default is the step's own intended starting value; falling straight to `min` (as
		// this used to) is wrong for any param whose sensible default isn't its minimum --
		// grow_segmentation.k defaults to 15, not its min of 3.
		out[p.key] = p.default !== undefined
			? p.default
			: (p.kind === 'number' ? (p.min ?? 0) : (p.options?.[0]?.value ?? ''));
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

const scope = (op: string) => scopeOf(op, STEP_META[op]?.tier ?? 'derived');
const isRunnable = (op: string) =>
	scope(op) === 'view' && op !== 'getis_ord';   // Gi* runs automatically on view settle

// Steps collapse to a one-line parameter summary so all 7 fit without scrolling; click the
// row to expand the editable controls. A step with a problem always stays expanded.
const expanded = ref<Set<string>>(new Set());
function toggleExpand(id: string) {
	const s = new Set(expanded.value);
	s.has(id) ? s.delete(id) : s.add(id);
	expanded.value = s;
}
function isExpanded(id: string): boolean {
	return expanded.value.has(id) || problemFor.value.has(id);
}
function paramSummary(s: RecipeStep): string {
	const specs = STEP_META[s.op]?.params ?? [];
	if (!specs.length) return '';
	return specs
		.map((p) => {
			const v = s.params[p.key];
			if (p.kind === 'select') {
				return p.options?.find((o) => o.value === String(v))?.label ?? String(v ?? '');
			}
			return `${p.label.toLowerCase()} ${v ?? '—'}`;
		})
		.join(' · ');
}

const bakeLabel = computed(() => {
	if (props.baking) return 'Baking on the host…';
	if (!props.baked) return 'Bake recipe';
	return props.bakeStale ? 'Bake recipe (edited)' : 'Re-bake recipe';
});
</script>

<template>
	<div class="recipe-panel">
		<button class="rp-collapse" @click="emit('update:collapsed', !collapsed)">
			<span class="rp-chev">{{ collapsed ? '▸' : '▾' }}</span>
			<span class="rp-title">Pipeline</span>
			<InfoTip :text="PANEL_HELP.recipe" wide placement="left" @click.stop />
			<span class="rp-spacer" />
			<span v-if="problems?.length" class="rp-badge err">{{ problems.length }} issue{{ problems.length > 1 ? 's' : '' }}</span>
			<span v-else-if="bakeStale && baked" class="rp-badge warn">edited</span>
		</button>

		<div v-if="problems?.length && !collapsed" class="rp-problems">
			<p v-for="p in problems" :key="p.stepId">{{ p.message }}</p>
		</div>

		<ol v-show="!collapsed" class="steps">
			<li
				v-for="(s, i) in recipe.steps" :key="s.id"
				:class="{ off: !s.on, broken: problemFor.has(s.id), open: isExpanded(s.id) }"
			>
				<div class="step-head" @click="toggleExpand(s.id)">
					<span class="step-n">{{ i + 1 }}</span>
					<input class="step-on" type="checkbox" :checked="s.on" :title="s.on ? 'Disable this step' : 'Enable this step'" @click.stop @change="toggle(s.id)" />
					<span class="step-label">{{ STEP_META[s.op]?.label ?? s.op }}</span>
					<InfoTip
						v-if="STEP_HELP[s.op]"
						:title="STEP_HELP[s.op].summary"
						:text="STEP_HELP[s.op].detail"
						wide
						@click.stop
					/>
					<span class="rp-spacer" />
					<span class="scope" :class="scope(s.op)">
						{{ SCOPE_META[scope(s.op)].short }}
						<InfoTip :text="SCOPE_META[scope(s.op)].help" placement="left" @click.stop />
					</span>
					<button v-if="!DEFAULT_IDS.has(s.id)" class="rm" title="Remove this step" @click.stop.prevent="removeStep(s.id)">✕</button>
					<span class="step-chev">{{ isExpanded(s.id) ? '▾' : '▸' }}</span>
				</div>

				<p v-if="!isExpanded(s.id) && s.on && paramSummary(s)" class="step-summary">{{ paramSummary(s) }}</p>

				<template v-if="isExpanded(s.id)">
				<p v-if="problemFor.has(s.id)" class="step-err">{{ problemFor.get(s.id)!.message }}</p>
				<p v-else-if="s.on && skipped.has(s.op)" class="step-skip">
					Not shown in the live preview — Bake to compute it.
				</p>

				<div v-if="s.on && STEP_META[s.op]?.params.length" class="params">
					<label v-for="p in STEP_META[s.op].params" :key="p.key" class="param">
						<span class="param-label">
							{{ p.label }}
							<InfoTip v-if="STEP_HELP[s.op]?.params[p.key]" :text="STEP_HELP[s.op].params[p.key]" placement="left" />
						</span>
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

				<div v-if="s.on && s.op === 'grow_segmentation'" class="seed-bind">
					<span class="seed-title">
						Seed classes
						<InfoTip text="Each bound seed layer becomes one class, in this order. Paint at least two." placement="left" />
					</span>
					<p v-if="!seedLayerNames.length" class="seed-hint">paint a seed layer first (+ seed, under the Spatial view)</p>
					<label v-for="name in seedLayerNames" :key="name" class="seed-row">
						<input type="checkbox" :checked="seedBound(s).includes(name)" @change="toggleSeed(s.id, name)" />
						<span>{{ name }}</span>
						<span v-if="seedBound(s).includes(name)" class="seed-idx">class {{ seedBound(s).indexOf(name) }}</span>
					</label>
				</div>

				<button
					v-if="s.on && isRunnable(s.op) && !problemFor.has(s.id)"
					class="run-step-btn"
					:disabled="!!busyOp"
					:title="ACTION_HELP.runOnView"
					@click.prevent="emit('run-step', s.op as ViewportOp)"
				>
					{{ busyOp ? 'Running…' : '▸ Run on this view' }}
				</button>
				<p v-else-if="s.on && scope(s.op) === 'view' && !problemFor.has(s.id)" class="auto-note">
					recomputes automatically when you pan or zoom
				</p>
				</template>
			</li>
		</ol>

		<div class="add-step" v-if="!collapsed && addableOps.length">
			<select @change="addStep(($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).value = ''">
				<option value="">+ add step…</option>
				<optgroup v-for="g in addableByCategory" :key="g.cat" :label="g.label">
					<option v-for="op in g.ops" :key="op" :value="op">{{ STEP_META[op].label }}</option>
				</optgroup>
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
				<span v-if="previewing">updating live preview…</span>
				<span v-else-if="previewError" class="err">{{ previewError }}</span>
				<span v-else-if="previewMs != null">live preview · {{ previewMs }} ms · approximate</span>
				<span v-else-if="baked">showing the last bake</span>
			</div>
			<button
				class="bake-btn"
				:class="{ stale: bakeStale && baked }"
				:disabled="previewing || baking || !!problems?.length"
				:title="problems?.length ? 'Fix the issues above first' : ACTION_HELP.bake"
				@click="emit('bake')"
			>
				{{ bakeLabel }}
			</button>
		</div>
	</div>
</template>

<style scoped>
.recipe-panel { display: flex; flex-direction: column; height: 100%; min-height: 0; font-size: 12px; }
.rp-collapse {
	display: flex; align-items: center; gap: 6px; width: 100%; font: inherit; font-size: 11px;
	font-weight: 650; color: var(--text-dim, #94a3b8); background: none; border: none;
	border-bottom: 1px solid var(--border, rgba(255,255,255,0.08)); padding: 7px 10px;
	cursor: pointer; text-align: left;
}
.rp-chev { width: 9px; }
.rp-title { text-transform: uppercase; letter-spacing: 0.05em; }
.rp-spacer { flex: 1; }
.rp-badge { font-size: 9.5px; font-weight: 700; padding: 1px 6px; border-radius: 999px; text-transform: uppercase; letter-spacing: 0.03em; }
.rp-badge.err { background: color-mix(in srgb, #dc2626 26%, transparent); color: #fca5a5; }
.rp-badge.warn { background: color-mix(in srgb, #d97706 26%, transparent); color: #fcd34d; }

.rp-problems { padding: 7px 10px; background: color-mix(in srgb, #dc2626 12%, transparent); border-bottom: 1px solid color-mix(in srgb, #dc2626 30%, transparent); }
.rp-problems p { margin: 0 0 3px; font-size: 11px; color: #fca5a5; line-height: 1.4; }
.rp-problems p:last-child { margin-bottom: 0; }

.steps { list-style: none; margin: 0; padding: 0; overflow-y: auto; flex: 1; counter-reset: step; }
.steps li { border-bottom: 1px solid var(--border, rgba(255,255,255,0.08)); padding: 6px 10px; }
.steps li.off { opacity: 0.45; }
.steps li.broken { background: color-mix(in srgb, #dc2626 9%, transparent); opacity: 1; }
.steps li.open { background: rgba(255,255,255,0.02); }
.step-head { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.step-chev { flex: none; width: 10px; font-size: 9px; color: var(--text-dim, #94a3b8); text-align: center; }
.step-summary { margin: 3px 0 0 22px; font-size: 10px; color: var(--text-dim, #94a3b8); font-variant-numeric: tabular-nums; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.step-n {
	flex: none; width: 16px; height: 16px; border-radius: 4px; font-size: 9.5px; font-weight: 700;
	display: grid; place-items: center; color: var(--text-dim, #94a3b8);
	background: var(--bg-2, #111a33); font-variant-numeric: tabular-nums;
}
.step-on { cursor: pointer; margin: 0; }
.step-label { font-weight: 600; }
.scope { display: inline-flex; align-items: center; gap: 3px; font-size: 9px; text-transform: uppercase; letter-spacing: 0.04em; padding: 1px 5px; border-radius: 4px; white-space: nowrap; }
.scope.bake { background: color-mix(in srgb, #d97706 22%, transparent); color: #fcd34d; }
.scope.preview { background: color-mix(in srgb, #16a34a 22%, transparent); color: #86efac; }
.scope.view { background: color-mix(in srgb, #38bdf8 22%, transparent); color: #7dd3fc; }
.rm { border: none; background: none; color: var(--text-dim, #94a3b8); cursor: pointer; font-size: 11px; padding: 0 2px; }

.step-err { margin: 5px 0 0 22px; font-size: 10.5px; color: #fca5a5; line-height: 1.4; }
.step-skip { margin: 5px 0 0 22px; font-size: 10.5px; color: #fcd34d; font-style: italic; }
.auto-note { margin: 5px 0 0 22px; font-size: 10px; color: var(--text-dim, #94a3b8); font-style: italic; }

.params { display: grid; grid-template-columns: 1fr 1fr; gap: 5px 8px; margin-top: 6px; padding-left: 22px; }
.param { display: flex; flex-direction: column; gap: 2px; }
.param-label { display: inline-flex; align-items: center; gap: 3px; font-size: 10px; color: var(--text-dim, #94a3b8); }
.param input, .param select {
	font: inherit; font-size: 11px; padding: 3px 5px; background: var(--bg-2, #111a33);
	color: var(--text, #e5e7eb); border: 1px solid var(--border, rgba(255,255,255,0.14)); border-radius: 5px;
}
.seed-bind { margin-top: 6px; padding-left: 22px; display: flex; flex-direction: column; gap: 3px; }
.seed-title { display: inline-flex; align-items: center; gap: 4px; font-size: 10px; color: var(--text-dim, #94a3b8); }
.seed-hint { margin: 0; font-size: 10px; font-style: italic; color: var(--text-dim, #94a3b8); }
.seed-row { display: flex; align-items: center; gap: 6px; font-size: 11px; }
.seed-idx { font-size: 9px; color: var(--text-dim, #94a3b8); }

.run-step-btn {
	margin: 7px 0 0 22px; font: inherit; font-size: 10.5px; cursor: pointer; padding: 3px 9px;
	border-radius: 6px; color: #7dd3fc; background: color-mix(in srgb, #38bdf8 12%, transparent);
	border: 1px solid color-mix(in srgb, #38bdf8 40%, transparent);
}
.run-step-btn:disabled { opacity: 0.45; cursor: not-allowed; }

.add-step { padding: 6px 10px; border-bottom: 1px solid var(--border, rgba(255,255,255,0.08)); }
.add-step select { width: 100%; font-size: 11px; padding: 3px 5px; background: var(--bg-2, #111a33); color: var(--text, #e5e7eb); border: 1px solid var(--border, rgba(255,255,255,0.14)); border-radius: 5px; }
.rp-footer { flex-shrink: 0; border-top: 1px solid var(--border, rgba(255,255,255,0.12)); padding: 8px 10px; display: flex; flex-direction: column; gap: 6px; }
.preview-line { font-size: 11px; color: var(--text-dim, #94a3b8); font-style: italic; min-height: 14px; }
.preview-line .err { color: var(--danger, #fca5a5); font-style: normal; }
.bake-btn {
	font: inherit; font-size: 12px; font-weight: 650; cursor: pointer; padding: 7px 12px; border-radius: 7px;
	color: var(--accent-ink, #0b1020); background: var(--accent, #38bdf8); border: 1px solid var(--accent, #38bdf8);
}
.bake-btn.stale { background: #fbbf24; border-color: #fbbf24; }
.bake-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
