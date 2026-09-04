import { describe, expect, it } from 'vitest';
import { diagRequestError, DiagRequestError } from './diagError';

const NOT_PERMITTED = JSON.stringify({ detail: 'not permitted' });

describe('diagRequestError', () => {
	it('turns the reported 401 into a sentence naming the cause and the fix', () => {
		const e = diagRequestError('preview', 401, NOT_PERMITTED);
		// The exact string the analyst saw must not survive anywhere in the message.
		expect(e.message).not.toMatch(/401|not permitted|\{/);
		expect(e.message).toBe('Your session expired. Reload the page to sign in again.');
	});

	it('treats 403 the same as 401 — both mean "sign in again" once refresh has failed', () => {
		expect(diagRequestError('preview', 403, NOT_PERMITTED).message)
			.toBe(diagRequestError('preview', 401, NOT_PERMITTED).message);
	});

	it('keeps the raw body on the error for the console but never in the message', () => {
		const e = diagRequestError('preview', 401, NOT_PERMITTED);
		expect(e).toBeInstanceOf(DiagRequestError);
		expect(e.detail).toBe(NOT_PERMITTED);
		expect(e.status).toBe(401);
	});

	it('says a cut is unbaked rather than reporting a conflict', () => {
		expect(diagRequestError('viewport', 409, JSON.stringify({ detail: 'analysis has no completed bake' })).message)
			.toBe('This cut has not been baked yet — run a bake first.');
	});

	it('passes a 422 recipe fault through, because the service detail is already prose', () => {
		const body = JSON.stringify({
			detail: "recipe failed: step 's5' (getis_ord) requires ['resid_z']",
		});
		const e = diagRequestError('preview', 422, body);
		expect(e.message).toContain("This recipe can't run:");
		expect(e.message).toContain('getis_ord');
	});

	it('falls back to a generic sentence for a 422 with no usable detail', () => {
		expect(diagRequestError('preview', 422, '<html>gateway</html>').message)
			.toBe("This recipe can't run as written.");
	});

	it('reports 404 as a missing diagnostics row', () => {
		expect(diagRequestError('preview', 404, '').message).toBe('This cut has no diagnostics row.');
	});

	it('groups the 5xx family into one retryable sentence', () => {
		for (const s of [502, 503, 504]) {
			expect(diagRequestError('preview', s, '').message)
				.toBe('The diagnostics service is unavailable. Try again in a moment.');
		}
	});

	it('names the operation only in the unmapped fallback', () => {
		expect(diagRequestError('viewport recompute', 418, '').message)
			.toBe('Diagnostics viewport recompute failed (HTTP 418).');
	});

	it('truncates a large body rather than carrying it whole', () => {
		expect(diagRequestError('preview', 500, 'x'.repeat(5000)).detail).toHaveLength(500);
	});
});
