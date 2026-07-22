// FRM signal-filter chain: types, defaults, hashing, and filter-service calls
// (docs/superpowers/specs/2026-07-21-frm-filtering-suite-design.md). The chain JSON shape
// is shared verbatim with the filter-service (scipy) and MATLAB frm_filters (bake).
import { type Cache, parseCache } from './liveCache';

export interface FilterChain {
	despike: { on: boolean; window: number; sigma: number };
	detrend: { on: boolean; mode: 'dc' | 'highpass'; cutoff_hz: number };
	lowpass: { on: boolean; cutoff_hz: number; order: number };
	notch: { on: boolean; harmonics: number[]; q: number };
}

export function defaultChain(): FilterChain {
	return {
		despike: { on: false, window: 11, sigma: 5 },
		detrend: { on: false, mode: 'highpass', cutoff_hz: 5 },
		lowpass: { on: false, cutoff_hz: 2000, order: 4 },
		notch: { on: false, harmonics: [1, 2, 3], q: 30 },
	};
}

export function chainActive(c: FilterChain | null | undefined): boolean {
	return !!c && (c.despike.on || c.detrend.on || c.lowpass.on || c.notch.on);
}

// Only the enabled stages matter for identity (toggling params of a disabled stage
// shouldn't refetch); stable key order via manual serialisation.
export function chainKey(c: FilterChain): string {
	const parts: string[] = [];
	if (c.despike.on) parts.push(`d${c.despike.window}_${c.despike.sigma}`);
	if (c.detrend.on) parts.push(`t${c.detrend.mode}_${c.detrend.cutoff_hz}`);
	if (c.lowpass.on) parts.push(`l${c.lowpass.cutoff_hz}_${c.lowpass.order}`);
	if (c.notch.on) parts.push(`n${c.notch.harmonics.join('.')}_${c.notch.q}`);
	return parts.join('|') || 'raw';
}

export function chainSummary(c: FilterChain | null | undefined): string {
	if (!c) return '';
	const s: string[] = [];
	if (c.despike.on) s.push(`despike ${c.despike.sigma}σ`);
	if (c.detrend.on) s.push(c.detrend.mode === 'dc' ? 'DC removal' : `HP ${c.detrend.cutoff_hz} Hz`);
	if (c.lowpass.on) s.push(`LP ${c.lowpass.cutoff_hz} Hz`);
	if (c.notch.on) s.push(`notch ${c.notch.harmonics.join(',')}× Q${c.notch.q}`);
	return s.join(' · ');
}

// ---- filter-service calls (same-origin via Caddy /filter/*; Directus session cookie
// flows automatically, and the service forwards it when fetching the cache) ----
export async function fetchFiltered(cacheFileId: string, chain: FilterChain, targetPoints = 1_500_000, signal?: AbortSignal):
	Promise<{ cache: Cache; skipped: string[]; stride: number }> {
	const res = await fetch('/filter/run', {
		method: 'POST',
		credentials: 'include',
		signal,
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ cache_file_id: cacheFileId, chain, target_points: targetPoints }),
	});
	if (!res.ok) throw new Error(`filter service: ${res.status} ${(await res.text()).slice(0, 200)}`);
	const skipped = (res.headers.get('X-Filter-Skipped') || '').split(';').map((s) => s.trim()).filter(Boolean);
	const stride = Math.max(1, parseInt(res.headers.get('X-Filter-Stride') || '1', 10) || 1);
	return { cache: parseCache(await res.arrayBuffer()), skipped, stride };
}

export async function fetchFilteredFft(cacheFileId: string, chain: FilterChain, axis: string):
	Promise<{ f: number[]; amp: number[] }> {
	const res = await fetch('/filter/fft', {
		method: 'POST',
		credentials: 'include',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ cache_file_id: cacheFileId, chain, axis }),
	});
	if (!res.ok) throw new Error(`filter service: ${res.status}`);
	return res.json();
}
