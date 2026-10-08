// What a Figure / Lite / Full view is doing while it is not yet showing the finished picture
// (#102). One vocabulary for the three renderers so they say the same thing in the same place:
// "Downloading live cache 42%", "Building cloud…", "Streaming full-res 63%".
export type LoadStage =
	| { kind: 'download'; loaded: number; total: number | null; what?: string }
	| { kind: 'build' }
	| { kind: 'open' }
	| { kind: 'stream'; fraction: number | null };

/**
 * What a renderer reports to its host: the busy mark on the active view-type button (label,
 * progress) and the host's loading overlay (the raw stage).
 */
export interface StageInfo { label: string; progress: number | null; stage: LoadStage }

const mb = (n: number) => `${(n / 1048576).toFixed(n >= 10 * 1048576 ? 0 : 1)} MB`;
const pct = (f: number) => `${Math.round(Math.max(0, Math.min(1, f)) * 100)}%`;

export function stageProgress(s: LoadStage): number | null {
	if (s.kind === 'download') return s.total && s.total > 0 ? Math.max(0, Math.min(1, s.loaded / s.total)) : null;
	if (s.kind === 'stream') return s.fraction;
	return null;
}

export function stageLabel(s: LoadStage): string {
	switch (s.kind) {
		case 'download': {
			const what = s.what ?? 'live cache';
			const p = stageProgress(s);
			// Content-Length can be missing (compressed / chunked): say how much has arrived instead.
			return p != null ? `Downloading ${what} ${pct(p)}` : s.loaded > 0 ? `Downloading ${what} ${mb(s.loaded)}` : `Downloading ${what}…`;
		}
		case 'build': return 'Building cloud…';
		case 'open': return 'Opening full-res octree…';
		case 'stream': return s.fraction != null ? `Streaming full-res ${pct(s.fraction)}` : 'Streaming full-res…';
	}
}

export function stageInfo(s: LoadStage | null): StageInfo | null {
	return s ? { label: stageLabel(s), progress: stageProgress(s), stage: s } : null;
}

/**
 * Is the LOD octree still streaming nodes in? There is no "done" signal from the loader, so this
 * reads the visible-point count: done once it reaches (nearly) everything the map has, or once it
 * has stopped changing for a while (a budget-capped map never reaches the total).
 */
export function streamStage(visible: number, total: number | null | undefined, idleMs: number): LoadStage | null {
	if (idleMs > 3000) return null;
	if (visible > 0 && idleMs > 1200) return null;
	if (total && total > 0 && visible >= 0.97 * total) return null;
	return { kind: 'stream', fraction: total && total > 0 && visible > 0 ? Math.min(1, visible / total) : null };
}

/** Quantise a stage so a per-frame caller only writes reactive state when the label would change. */
export function sameStage(a: LoadStage | null, b: LoadStage | null): boolean {
	if (a === b) return true;
	if (!a || !b) return false;
	return stageLabel(a) === stageLabel(b);
}

/** The FRM view that is on screen (after fallbacks), not just the one the user asked for. */
export type OverlayMode = 'figure' | 'lite' | 'full';

/**
 * The one loading overlay the Plot page draws over the FRM area (#191), whichever view type is on
 * screen. 'veil' is the centred spinner + label + progress bar; 'pill' is the small corner badge for
 * a Full octree that is already showing its cloud while LOD nodes stream in.
 *
 * Lite and Full report their stage through `stage` (the renderer's @stage); Figure has no renderer,
 * so its download shows while `figLoading` is set, from `figStage` (null = request not yet sized).
 * The figure download only counts in Figure mode: the Figure PNG is also fetched in the background
 * for Lite / Full, and must not label those views.
 */
export interface FrmOverlay { variant: 'veil' | 'pill'; stage: LoadStage }
export function frmOverlay(mode: OverlayMode, stage: LoadStage | null, figLoading: boolean, figStage: LoadStage | null = null): FrmOverlay | null {
	const s = mode === 'figure' ? (figLoading ? (figStage ?? { kind: 'download', loaded: 0, total: null, what: 'figure' }) : null) : stage;
	return s ? { variant: s.kind === 'stream' ? 'pill' : 'veil', stage: s } : null;
}
