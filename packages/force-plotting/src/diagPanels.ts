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

// Fits in ~16 rows so the responsive row-height stays generous. The Pipeline column runs the
// full height (7 steps + parameters need the room); Signal and Clusters share a band under
// the hero Spatial view; the Selection inspector is a thin strip along the bottom.
export const DIAG_DEFAULT_LAYOUT: DiagPanelInst[] = [
	{ i: 'spatial', type: 'spatial', x: 0, y: 0, w: 9, h: 9, channel: 'residZ' },
	{ i: 'recipe', type: 'recipe', x: 9, y: 0, w: 3, h: 13 },
	{ i: 'signal', type: 'signal', x: 0, y: 9, w: 4, h: 4 },
	{ i: 'clusters', type: 'clusters', x: 4, y: 9, w: 5, h: 4 },
	{ i: 'inspector', type: 'inspector', x: 0, y: 13, w: 9, h: 3 },
];

export const DIAG_LAYOUT_LS_KEY = 'force-app.diag.layout.v2';

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
