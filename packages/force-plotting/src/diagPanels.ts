// Panel model for the Diagnostics Workbench, the same shape the Record tab uses
// (apps/force-app/web/src/record/RecordPage.vue): a registry of panel types, a persisted
// layout of instances, and add / close / reset. `spatial` is multi-instance so an analyst can
// put two full-resolution views side by side on different channels; the rest are single.

export interface DiagPanelType {
	title: string;
	icon: string;
	/** at most one instance when true. */
	single?: boolean;
	/** grid cells for a newly-added instance. */
	w: number;
	h: number;
}

export const DIAG_PANEL_TYPES: Record<string, DiagPanelType> = {
	spatial: { title: 'Spatial view', icon: 'scatter_plot', w: 6, h: 12 },
	recipe: { title: 'Pipeline', icon: 'tune', single: true, w: 3, h: 8 },
	signal: { title: 'Signal', icon: 'show_chart', single: true, w: 3, h: 5 },
	clusters: { title: 'Clusters', icon: 'workspaces', single: true, w: 3, h: 6 },
	inspector: { title: 'Selection inspector', icon: 'query_stats', single: true, w: 3, h: 4 },
};

export interface DiagPanelInst {
	/** stable unique id; grid key and per-panel state key. */
	i: string;
	type: string;
	x: number;
	y: number;
	w: number;
	h: number;
	/** spatial panels only: which channel this view colours by. */
	channel?: string;
}

// Phase H slice 3: pipeline LEFT, full height (an analyst reads it top to bottom while
// setting up a recipe, the same way they read a card list) with the Spatial view as the HERO
// -- top two thirds of the remaining width -- since it is what most eyes are on once the
// recipe is dialled in. Signal and Clusters share a band under it; the Selection inspector is
// a thin strip along the bottom. Fits in 16 rows so the responsive row-height stays generous.
export const DIAG_DEFAULT_LAYOUT: DiagPanelInst[] = [
	{ i: 'recipe', type: 'recipe', x: 0, y: 0, w: 3, h: 16 },
	{ i: 'spatial', type: 'spatial', x: 3, y: 0, w: 9, h: 11, channel: 'residZ' },
	{ i: 'signal', type: 'signal', x: 3, y: 11, w: 4, h: 3 },
	{ i: 'clusters', type: 'clusters', x: 7, y: 11, w: 5, h: 3 },
	{ i: 'inspector', type: 'inspector', x: 3, y: 14, w: 9, h: 2 },
];

// Bumped v2 -> v3 for the pipeline-left rework above: without this, every analyst with a
// persisted layout keeps their old (spatial-left) arrangement and never sees the new default.
export const DIAG_LAYOUT_LS_KEY = 'force-app.diag.layout.v3';

export function loadDiagLayout(): DiagPanelInst[] {
	try {
		const s = JSON.parse(localStorage.getItem(DIAG_LAYOUT_LS_KEY) || 'null');
		if (Array.isArray(s) && s.length && s.every((x) => x?.i && x?.type && DIAG_PANEL_TYPES[x.type])) {
			return s as DiagPanelInst[];
		}
	} catch { /* fall through to default */ }
	return DIAG_DEFAULT_LAYOUT.map((x) => ({ ...x }));
}

export function saveDiagLayout(layout: DiagPanelInst[]): void {
	try { localStorage.setItem(DIAG_LAYOUT_LS_KEY, JSON.stringify(layout)); } catch { /* private mode */ }
}

/** A new instance of `type`, placed below everything currently in `layout`. */
export function newPanelInst(type: string, layout: DiagPanelInst[]): DiagPanelInst | null {
	const meta = DIAG_PANEL_TYPES[type];
	if (!meta) return null;
	if (meta.single && layout.some((p) => p.type === type)) return null;
	const maxY = layout.reduce((m, p) => Math.max(m, p.y + p.h), 0);
	const id = `${type}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`;
	const inst: DiagPanelInst = { i: id, type, x: 0, y: maxY, w: meta.w, h: meta.h };
	if (type === 'spatial') inst.channel = 'residZ';
	return inst;
}
