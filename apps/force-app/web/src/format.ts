// Shared display formatters. Elapsed-time readouts used to have three near-identical local copies
// (OverviewPanel.vue, TransportBar.vue, AppShell.vue's recording banner) — a future fix (e.g.
// supporting hour-long recordings everywhere) had to be found and applied in each one separately.

/** m:ss, or h:mm:ss once past an hour. For plain elapsed-time readouts; OverviewPanel's live tile
 *  additionally shows sub-second precision under a minute, which is a deliberate visual choice for
 *  that one tile rather than something every caller needs. */
export function formatDuration(sec: number): string {
	if (!Number.isFinite(sec) || sec < 0) return '0:00';
	const s = Math.floor(sec);
	const m = Math.floor(s / 60);
	const rem = s % 60;
	if (m < 60) return `${m}:${String(rem).padStart(2, '0')}`;
	const h = Math.floor(m / 60);
	return `${h}:${String(m % 60).padStart(2, '0')}:${String(rem).padStart(2, '0')}`;
}
