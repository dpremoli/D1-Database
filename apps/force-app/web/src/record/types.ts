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
