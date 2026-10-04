// Resumable upload of one capture (stream-2 review 2.2). The save is three steps: the
// manufacturing_operations row, the capture's files (/files), then the machining_force_analysis
// row. A failure in step 2 or 3 used to be retried from step 1, inserting a second operation row
// and uploading the files again. Each step now records what it finished, keyed by capture id, so a
// retry (from the save dialog or from Settings > Local Captures) continues where it stopped.
//
// A response can also be lost after the server committed (a timeout), so before inserting again
// the operation is looked up by the capture id both upload paths stamp into
// recorded_metadata.capture_id. Directus cannot filter on a key inside that JSON field
// (captureUploadState.ts), so candidate rows are fetched by created_at and matched here.
import { api } from '../directusClient';
import { matchUploaded, uploadedRowsSince } from '../settings/captureUploadState';

export interface UploadProgress {
	/** manufacturing_operations row for this capture, once created (or found). */
	opId?: string;
	/** An insert has been sent: its response may have been lost, so look before sending another. */
	insertAttempted?: boolean;
	/** undefined = not uploaded yet; null = nothing to upload (no capture.mat was written). */
	matFileId?: string | null;
	cacheFileId?: string;
	/** The machining_force_analysis row exists. */
	analysisDone?: boolean;
}

const progressByCapture = new Map<string, UploadProgress>();

export function uploadProgress(captureId: string): UploadProgress {
	let p = progressByCapture.get(captureId);
	if (!p) { p = {}; progressByCapture.set(captureId, p); }
	return p;
}
export function clearUploadProgress(captureId?: string): void {
	if (captureId) progressByCapture.delete(captureId); else progressByCapture.clear();
}

/** The operation id already stamped with this capture id, or null. Throws when the lookup fails. */
export async function findOperationForCapture(captureId: string): Promise<string | null> {
	const since = uploadedRowsSince([captureId]);
	const res = await api.get('/items/manufacturing_operations', {
		params: {
			filter: { recorded_metadata: { _nnull: true }, ...(since ? { created_at: { _gte: since } } : {}) },
			fields: ['operation_id', 'recorded_metadata'], sort: '-created_at', limit: -1,
		},
	});
	return matchUploaded(res.data?.data ?? [], [captureId]).opIds[captureId] ?? null;
}

/** Whether an analysis row already links to this operation. Throws when the lookup fails. */
export async function hasAnalysisRow(opId: string): Promise<boolean> {
	const res = await api.get('/items/machining_force_analysis', {
		params: { filter: { operation_id: { _eq: opId } }, fields: ['id'], limit: 1 },
	});
	return (res.data?.data?.length ?? 0) > 0;
}

/**
 * The operation row for this capture: the one remembered from an earlier attempt, one found by
 * capture id (when an earlier insert may have been committed without us seeing the reply, or
 * `alwaysLookup`), or a freshly inserted one. `existing` is true unless `insert` ran now.
 */
export async function ensureOperation(
	captureId: string, p: UploadProgress, insert: () => Promise<string>, alwaysLookup = false,
): Promise<{ opId: string; existing: boolean }> {
	if (p.opId) return { opId: p.opId, existing: true };
	if (p.insertAttempted || alwaysLookup) {
		// Best effort: if the lookup itself fails the insert below will most likely fail too, and
		// a failed lookup must not block an upload that would have worked.
		const found = await findOperationForCapture(captureId).catch(() => null);
		if (found) { p.opId = found; return { opId: found, existing: true }; }
	}
	p.insertAttempted = true;
	const opId = await insert();
	p.opId = opId;
	return { opId, existing: false };
}

/** Whether any file of this capture still has to be uploaded (so its blobs need fetching). */
export function needsBlobs(p: UploadProgress, matWritten: boolean): boolean {
	return p.cacheFileId === undefined || (matWritten && p.matFileId === undefined);
}

/**
 * True when the analysis row must not be posted again: it was created by an earlier attempt, or
 * the operation was an existing one that already has one (a lost reply).
 */
export async function analysisAlreadyLinked(p: UploadProgress, opId: string, existing: boolean): Promise<boolean> {
	if (p.analysisDone) return true;
	if (!existing) return false;
	try { p.analysisDone = await hasAnalysisRow(opId); } catch { /* unknown: carry on and post */ }
	return !!p.analysisDone;
}
