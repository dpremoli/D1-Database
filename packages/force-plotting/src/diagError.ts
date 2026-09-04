// Turning a sidecar HTTP failure into something an analyst can act on.
//
// Every diag client used to throw `${label}: ${status} ${body.slice(0, 200)}`, so a routine
// expired session reached the panel as `diag preview: 401 {"detail":"not permitted"}` — a
// message that names no cause and suggests no fix, and reads as though the analyst had
// broken something. The status codes the sidecar actually emits are few and each has one
// honest sentence. The raw body is kept on the error for the console; it never reaches the UI.

export class DiagRequestError extends Error {
	readonly status: number;
	/** Raw response body, for `console.warn`. Deliberately not shown to the analyst. */
	readonly detail: string;

	constructor(message: string, status: number, detail: string) {
		super(message);
		this.name = 'DiagRequestError';
		this.status = status;
		this.detail = detail;
	}
}

/** The `detail` field of a FastAPI HTTPException body, when the body is one. */
function serverDetail(body: string): string | null {
	try {
		const parsed = JSON.parse(body);
		const d = parsed?.detail;
		return typeof d === 'string' && d.trim() ? d.trim() : null;
	} catch {
		return null;
	}
}

/**
 * Build the error a diag client throws for a non-OK response.
 *
 * `what` names the operation in the analyst's terms ("preview", "viewport recompute") and is
 * only used by the fallback branch — the mapped messages read better without a prefix.
 */
export function diagRequestError(what: string, status: number, body: string): DiagRequestError {
	const detail = serverDetail(body);
	let message: string;
	switch (status) {
		case 401:
		case 403:
			// Reachable only after authorizedFetch's refresh-and-retry has already failed,
			// so the session really is gone — not a permissions puzzle to investigate.
			message = 'Your session expired. Reload the page to sign in again.';
			break;
		case 404:
			message = 'This cut has no diagnostics row.';
			break;
		case 409:
			message = 'This cut has not been baked yet — run a bake first.';
			break;
		case 422:
			// The service's 422 detail is already analyst-facing prose for recipe faults
			// (the same sentence recipeProblems() writes client-side).
			message = detail
				? `This recipe can't run: ${detail}`
				: "This recipe can't run as written.";
			break;
		case 502:
		case 503:
		case 504:
			message = 'The diagnostics service is unavailable. Try again in a moment.';
			break;
		default:
			message = `Diagnostics ${what} failed (HTTP ${status}).`;
	}
	return new DiagRequestError(message, status, body.slice(0, 500));
}
