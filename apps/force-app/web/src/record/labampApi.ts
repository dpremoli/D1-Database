// Frontend helper for the backend's /labamp/* endpoints (the backend proxies to the link-local
// Kistler amp; in dev it defaults to a mock so the UI works without hardware).
import { getConfig } from '../config';

function base() { return getConfig().recorderUrl; }

export interface LabAmpStatus { reachable: boolean; mode: string | null; base_url: string; mock: boolean; channels: number; config_mode: string; }
export interface SensorRow { channel: number; name?: string; serialNumber?: string; physicalQuantity?: string; sensitivity?: number; range?: number; }
export interface LabAmpConfig { base_url: string; channels: number; mode: string; autorange_headroom?: number; }
export interface AutoRangeRec { channel: number; peak: number; current: number | null; recommended: number; resolution: number; bits_used: number; would_clip: boolean; headroom: number; }
export interface AutoRangeResult { headroom: number; adc_bits: number; recommendations: AutoRangeRec[]; }

async function j<T>(res: Response): Promise<T> {
	if (!res.ok) throw new Error(`${res.status}: ${(await res.text()).slice(0, 160)}`);
	return res.json() as Promise<T>;
}

export const labamp = {
	status: () => fetch(`${base()}/labamp/status`).then(j<LabAmpStatus>),
	setMode: (mode: 'MEASURE' | 'RESET') => fetch(`${base()}/labamp/mode`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode }) }).then(j<{ mode: string }>),
	sensors: () => fetch(`${base()}/labamp/sensors`).then(j<{ sensors: SensorRow[] }>),
	getConfig: () => fetch(`${base()}/labamp/config`).then(j<LabAmpConfig>),
	setConfig: (cfg: Partial<LabAmpConfig>) => fetch(`${base()}/labamp/config`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cfg) }).then(j<LabAmpConfig>),
	exportUrl: () => `${base()}/labamp/export`,
	autorange: (headroom?: number) => fetch(`${base()}/labamp/autorange${headroom ? `?headroom=${headroom}` : ''}`).then(j<AutoRangeResult>),
	autorangeApply: (headroom: number) => fetch(`${base()}/labamp/autorange/apply`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ headroom }) }).then(j<{ applied: AutoRangeRec[]; status: Record<string, string> }>),
};
