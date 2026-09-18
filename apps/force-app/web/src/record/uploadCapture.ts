// Stand-alone (workspace-independent) upload of a finished capture into the database. Used by
// LocalCaptureView to retry an upload from a cold page load, where the live RecordClient/workspace
// from the recording session no longer exists (navigating away from /record unmounts it). Rebuilds
// what it can purely from summary.json's echoed RecordConfig + extra_metadata - it can't recover
// the Directus lookup selections (sample/operator/equipment/insert) the user made in the UI, since
// those were never persisted anywhere but the live session, so this produces a validly-linked but
// less-annotated manufacturing_operations row than the live-session upload does.
import { api } from '../directusClient';
import { resolveMachiningMethodId } from './directusLookups';
import { buildSeriesEnvelope, parseCache, type Cache } from '@d1/force-plotting';

export interface ColdUploadInfo {
	captureId: string;
	matUrl: string;
	cacheUrl: string;
	cfg: Record<string, any>; // RecordConfig.model_dump(), as echoed in summary.json's "config"
	peaks?: { Fx: number; Fy: number; Fz: number } | null;
	cache?: Cache | null; // already-parsed live_cache, if the caller has it (avoids re-fetching)
	matWritten?: boolean; // summary.json's top-level mat_written; false for captures over MAT_MAX_BYTES, which never got a capture.mat written
}

function directusErrorMessage(e: any): string {
	const status = e?.response?.status;
	const detail = e?.response?.data?.errors?.[0]?.message;
	if (status && detail) return `${status}: ${detail}`;
	if (status) return `${status}: ${e?.message || 'request failed'}`;
	return e?.message || String(e);
}

async function uploadFile(blob: Blob, filename: string): Promise<string> {
	const fd = new FormData();
	fd.append('file', blob, filename);
	try {
		const res = await api.post('/files', fd);
		return res.data.data.id;
	} catch (e: any) {
		throw new Error(`file upload (${filename}) failed - ${directusErrorMessage(e)}`);
	}
}

export async function uploadCaptureColdStart(info: ColdUploadInfo): Promise<string> {
	const cfg = info.cfg || {};
	const extra: Record<string, any> = cfg.extra_metadata || {};
	const surface = Math.PI * (Number(cfg.diam) || 0) * (Number(cfg.rpm) || 0) / 1000;
	const payload: Record<string, any> = {
		operation_date: new Date().toISOString(),
		process_category: 'machining',
		machining_operation_subtype: extra.op_type || null,
		machining_spindle_speed_rpm: cfg.rpm ?? null,
		machining_feed_mm_per_rev: cfg.feed ?? null,
		machining_workpiece_diameter_mm: cfg.diam ?? null,
		machining_cutting_speed_m_per_min: Number.isFinite(surface) ? Number(surface.toFixed(2)) : null,
		machining_force_captured: true,
		machining_tacho_used: true,
		machining_coolant_used: !!(extra.coolant && String(extra.coolant).trim()),
		capture_software: 'force-app',
		capture_frequency_khz: cfg.sample_rate ? Number((cfg.sample_rate / 1000).toFixed(3)) : null,
		outcome_notes: extra.notes || null,
		recorded_metadata: { ...extra, capture_id: info.captureId, peaks: info.peaks, source: cfg.source, uploaded_via: 'local-capture-retry' },
	};
	payload.method_id = await resolveMachiningMethodId(extra.op_type).catch(() => null);

	let res;
	try {
		res = await api.post('/items/manufacturing_operations', payload);
	} catch (e: any) {
		throw new Error(`logging the run failed - ${directusErrorMessage(e)}`);
	}
	const opId = res.data?.data?.operation_id;
	if (!opId) throw new Error('run was logged but the server did not return its operation_id - cannot link the capture');

	// A capture too large for the MAT5 format (see finalize.py's MAT_MAX_BYTES) never had a
	// capture.mat written at all -- fetching it would 404 and abort the whole retry. Same fix as
	// the live-session upload path (workspace.ts).
	const matWritten = info.matWritten !== false;
	const [matBlob, cacheBlob] = await Promise.all([
		matWritten
			? fetch(info.matUrl).then((r) => { if (!r.ok) throw new Error('capture.mat fetch failed'); return r.blob(); })
			: Promise.resolve(null),
		fetch(info.cacheUrl).then((r) => { if (!r.ok) throw new Error('live_cache.bin fetch failed'); return r.blob(); }),
	]);
	const [matFileId, cacheFileId] = await Promise.all([
		matBlob ? uploadFile(matBlob, `${info.captureId}.mat`) : Promise.resolve(null),
		uploadFile(cacheBlob, `${info.captureId}_live_cache.bin`),
	]);

	// Same fix as the live-session upload path (workspace.ts): the force/RPM charts on the Plot
	// page read from `series` (a JSONB min/max envelope), not from live_cache_file — without this
	// the row links up fine (peaks, FRM) but every chart renders "no data" forever.
	let series: ReturnType<typeof buildSeriesEnvelope> | null = null;
	try {
		const cache = info.cache ?? parseCache(await cacheBlob.arrayBuffer());
		series = buildSeriesEnvelope(cache);
	} catch { /* best-effort — a missing series just means blank charts, not a failed upload */ }

	try {
		await api.post('/items/machining_force_analysis', {
			operation_id: opId,
			directus_files_id: matFileId,
			live_cache_file: cacheFileId,
			status: 'done',
			sample_rate: cfg.sample_rate ?? null,
			feed: cfg.feed ?? null,
			cut_diameter: cfg.diam ?? null,
			max_rpm: cfg.rpm ?? null,
			peak_fx: info.peaks?.Fx ?? null,
			peak_fy: info.peaks?.Fy ?? null,
			peak_fz: info.peaks?.Fz ?? null,
			series,
			matlab_version: 'force-app-direct',
			processed_at: new Date().toISOString(),
		});
	} catch (e: any) {
		throw new Error(`linking the capture failed - ${directusErrorMessage(e)} (the run was logged as operation ${opId}, and both files uploaded, but the analysis record could not be created)`);
	}
	return opId;
}
