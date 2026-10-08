// A pop-out window's settings live in its URL query (#108). The panel that opens the window builds
// the query, LivePanelWindow parses it on load and writes it back (history.replaceState) whenever
// something changes inside the window. The desktop shell saves each pop-out's *current URL* at
// quit and reopens it, so a change made in the window is remembered only if it is in the URL.
//
// Parsed field by field: a hand-edited, stale or truncated URL falls back to each field's default
// instead of reaching a plot as NaN or an unknown enum, and one bad field never costs the others.
import { COLORMAPS } from '@d1/force-plotting';
import { SUB_NAMES } from './liveClient';
import { PLOT_MODES } from './plotModes';
import { FRM_STRIDES } from './plotPrefs';
import { clampWindowSec, DEFAULT_WINDOW_SEC } from './plotWindow';

export type PopoutPanel = 'force' | 'frm' | 'polar';
export type FrmAxis = 'Fx' | 'Fy' | 'Fz';
export type PolarRadius = 'Fz' | 'Fxy' | 'Mz';
export type PolarAngle = 'tacho' | 'force_vector';

export interface PopoutState {
	mode: string;
	channels: string[];
	windowSec: number;
	colormap: string;
	pointSize: number;
	frmAxis: FrmAxis;
	stride: number;
	radius: PolarRadius;
	angle: PolarAngle;
}

export const SUMMED_CHANNELS = ['Fx', 'Fy', 'Fz'];
/** Channel pick order: the summed axes, then the sub-sensors. */
export const CHANNEL_ORDER: string[] = [...SUMMED_CHANNELS, ...SUB_NAMES];

export const POPOUT_DEFAULTS: PopoutState = {
	mode: 'time',
	channels: [...SUMMED_CHANNELS],
	windowSec: DEFAULT_WINDOW_SEC,
	colormap: 'viridis',
	pointSize: 2.2,
	frmAxis: 'Fz',
	stride: 1,
	radius: 'Fz',
	angle: 'tacho',
};

/** Which state fields each pop-out carries in its URL. */
const KEYS: Record<PopoutPanel, (keyof PopoutState)[]> = {
	force: ['mode', 'channels', 'windowSec'],
	frm: ['colormap', 'pointSize', 'frmAxis', 'stride'],
	polar: ['radius', 'angle', 'colormap', 'pointSize'],
};

// URL parameter names; kept as the ones the opener has always used so URLs saved by an older build
// still restore.
const PARAM: Record<keyof PopoutState, string> = {
	mode: 'mode', channels: 'channels', windowSec: 'window', colormap: 'colormap',
	pointSize: 'pointSize', frmAxis: 'frmAxis', stride: 'stride', radius: 'radius', angle: 'angle',
};

function oneOf<T extends string>(v: string | null, allowed: readonly T[], d: T): T {
	return allowed.includes(v as T) ? (v as T) : d;
}

/** Query string (or a URLSearchParams) -> a complete, valid state. Never throws. */
export function parsePopoutQuery(search: string | URLSearchParams): PopoutState {
	const q = typeof search === 'string' ? new URLSearchParams(search) : search;
	const d = POPOUT_DEFAULTS;

	const picked = new Set((q.get(PARAM.channels) || '').split(',').filter((c) => CHANNEL_ORDER.includes(c)));
	const channels = CHANNEL_ORDER.filter((c) => picked.has(c));

	const cm = q.get(PARAM.colormap);
	const ps = q.get(PARAM.pointSize);
	const psNum = ps !== null && ps.trim() !== '' ? Number(ps) : NaN;
	const st = q.get(PARAM.stride);
	const stNum = st !== null && st.trim() !== '' ? Number(st) : NaN;

	return {
		mode: oneOf(q.get(PARAM.mode), PLOT_MODES.map((m) => m.key as string), d.mode),
		channels: channels.length ? channels : [...d.channels],
		windowSec: clampWindowSec(q.get(PARAM.windowSec), d.windowSec),
		colormap: cm !== null && Object.prototype.hasOwnProperty.call(COLORMAPS, cm) ? cm : d.colormap,
		pointSize: Number.isFinite(psNum) ? Math.min(5, Math.max(1, psNum)) : d.pointSize,
		frmAxis: oneOf(q.get(PARAM.frmAxis), ['Fx', 'Fy', 'Fz'] as const, d.frmAxis),
		stride: FRM_STRIDES.includes(stNum) ? stNum : d.stride,
		radius: oneOf(q.get(PARAM.radius), ['Fz', 'Fxy', 'Mz'] as const, d.radius),
		angle: oneOf(q.get(PARAM.angle), ['tacho', 'force_vector'] as const, d.angle),
	};
}

/** The query for `panel`'s pop-out: only the fields that panel uses. */
export function buildPopoutQuery(panel: PopoutPanel, state: Partial<PopoutState>): URLSearchParams {
	const s = { ...POPOUT_DEFAULTS, ...state };
	const q = new URLSearchParams();
	for (const k of KEYS[panel]) {
		const v = s[k];
		q.set(PARAM[k], Array.isArray(v) ? v.join(',') : String(v));
	}
	return q;
}
