// Guard for long-running work (host-build polls, bakes) that was started for ONE operation and
// must not touch state once the user has moved on. A poll can run for 15 minutes; in that time the
// operator can open another op, leave the page (keep-alive deactivate) or unmount the dashboard.
// Without a guard the poll's result is written into whichever op is open by then (#review 3.1).
//
//   const live = guard.begin(d.id);
//   await somethingSlow();
//   if (!live()) return;            // op changed, or cancelAll() was called: touch nothing
export interface OpGuard {
	/** Start guarding work for `opId`; the returned function is true while that work is still wanted. */
	begin(opId: string | null | undefined): () => boolean;
	/** Make every guard handed out so far stale (op switched, deactivate, unmount). */
	cancelAll(): void;
}

export function createOpGuard(currentOpId: () => string | null | undefined): OpGuard {
	let epoch = 0;
	return {
		begin(opId) {
			const mine = epoch;
			return () => mine === epoch && opId != null && currentOpId() === opId;
		},
		cancelAll() { epoch++; },
	};
}
