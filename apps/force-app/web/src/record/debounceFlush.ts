// A trailing debounce that can also be flushed. Used for the pop-out's URL write-back: Chromium
// throttles history.replaceState (about 200 calls per 10 s), so a fast slider drag could drop the
// last value. Calls collapse into one write `ms` after the last change, and flush() runs a pending
// write immediately (pagehide / beforeunload), so a clean quit still saves the final URL.

export interface DebouncedFlush {
	call(): void;
	/** Runs the pending call now; does nothing when none is pending. */
	flush(): void;
	cancel(): void;
}

export function debounceFlush(fn: () => void, ms: number): DebouncedFlush {
	let timer: ReturnType<typeof setTimeout> | null = null;
	const cancel = () => { if (timer !== null) { clearTimeout(timer); timer = null; } };
	return {
		call() {
			cancel();
			timer = setTimeout(() => { timer = null; fn(); }, ms);
		},
		flush() {
			if (timer === null) return;
			cancel();
			fn();
		},
		cancel,
	};
}
