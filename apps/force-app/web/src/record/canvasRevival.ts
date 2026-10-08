// A canvas Chromium discards while its window is hidden or minimised comes back blank (#189), and
// both force plots skip a redraw when their data has not changed, so it stayed blank until the
// window slider changed something. This wires the events that mean "the bitmap may be gone" to a
// single repaint callback; the plots pass their own resize(), which re-sizes the canvas (resetting
// its transform, which a restored 2D context has lost), drops cached layers and schedules a draw.

interface Hub { addEventListener(type: string, fn: (e: Event) => void): void; removeEventListener(type: string, fn: (e: Event) => void): void }

/**
 * Call `repaint` when `canvas` fires `contextrestored`, when `doc` becomes visible again, and when
 * `win` regains focus. `contextlost` is cancelled so the browser is allowed to restore the context.
 * Returns the function that removes every listener.
 */
export function onCanvasRevival(
	canvas: Hub | null | undefined,
	doc: Hub & { hidden?: boolean },
	win: Hub,
	repaint: () => void,
): () => void {
	const onLost = (e: Event) => e.preventDefault();
	const onRestored = () => repaint();
	const onVisible = () => { if (!doc.hidden) repaint(); };
	const onFocus = () => repaint();
	canvas?.addEventListener('contextlost', onLost);
	canvas?.addEventListener('contextrestored', onRestored);
	doc.addEventListener('visibilitychange', onVisible);
	win.addEventListener('focus', onFocus);
	return () => {
		canvas?.removeEventListener('contextlost', onLost);
		canvas?.removeEventListener('contextrestored', onRestored);
		doc.removeEventListener('visibilitychange', onVisible);
		win.removeEventListener('focus', onFocus);
	};
}
