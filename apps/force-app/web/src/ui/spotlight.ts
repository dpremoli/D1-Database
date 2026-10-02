// Point the user at one GUI element (#98): scroll it into view and mark it for a moment. A
// string target is a `data-focus` id. Minimal on purpose — the styled ring lives with the
// `.spotlight` class in styles.css.
export function spotlight(target: Element | string, opts?: { durationMs?: number }): void {
	const el = typeof target === 'string' ? document.querySelector(`[data-focus="${target}"]`) : target;
	if (!el) return;
	el.scrollIntoView({ block: 'center' });
	el.classList.add('spotlight');
	window.setTimeout(() => el.classList.remove('spotlight'), opts?.durationMs ?? 2500);
}
