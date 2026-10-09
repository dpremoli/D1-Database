// Manual "Start FRM now" (#184): helpers for when the causal cut detector never fires.

/**
 * True while the live FRM is held at its origin waiting for the cut start: a live recording whose
 * "Detect cut start" option is on and where no cut start (auto or manual) has arrived yet. With the
 * option off the FRM already runs from the first sample, so there is nothing to wait for.
 */
export function frmWaitingForCut(state: string, frmFromCut: boolean, cutStartSec: number | null): boolean {
	return state === 'recording' && frmFromCut && cutStartSec === null;
}

/** The reason in a refused POST /record/cut-start (FastAPI's `{"detail": "..."}`), for the panel. */
export function cutStartRefusal(status: number, body: string): string {
	try {
		const d = JSON.parse(body)?.detail;
		if (typeof d === 'string' && d) return d;
	} catch { /* not JSON: fall through */ }
	return `The recorder refused (${status})${body ? `: ${body.slice(0, 160)}` : ''}`;
}
