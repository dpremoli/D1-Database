// Recording config sent to the backend /record/start (mirrors app/config.py::RecordConfig;
// all fields optional on the wire — the backend supplies defaults).
export interface RecordConfig {
	sample_name?: string;
	rpm?: number;
	feed?: number;
	diam?: number;
	inner_diam?: number;
	sample_rate?: number;
	duration_sec?: number;
	ppr?: number;
	axis?: 'Fx' | 'Fy' | 'Fz';
}

export type Axis = 'Fx' | 'Fy' | 'Fz';

export const AXIS_COLOR: Record<'Fx' | 'Fy' | 'Fz', string> = {
	Fx: '#dc2626',
	Fy: '#16a34a',
	Fz: '#2563eb',
};

// Per-channel colours for the live plot: summed axes keep their canonical hue; each dyno
// sub-channel gets a distinct shade grouped by its parent axis (red-ish / green-ish / blue-ish).
export const CH_COLOR: Record<string, string> = {
	Fx: '#f87171', Fy: '#4ade80', Fz: '#60a5fa',
	Fx1: '#f87171', Fx2: '#fca5a5',
	Fy1: '#4ade80', Fy2: '#86efac',
	Fz1: '#60a5fa', Fz2: '#93c5fd', Fz3: '#38bdf8', Fz4: '#818cf8',
};
