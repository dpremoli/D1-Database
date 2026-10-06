// Touch long-press -> context menu. A touchscreen has no right button, and iOS Safari fires no
// `contextmenu` on a hold (Android Chrome does, on its own timing), so the map views and the env
// charts open their menus from this instead: one finger held within a small slop for ~500 ms.
//
// Pure of the DOM (it takes the few PointerEvent fields it reads and uses setTimeout), so it is
// unit-tested with fake timers. Mouse and pen presses are ignored: the mouse has the real right
// button (createClickTracker in cloudPick.ts), and a pen's barrel button reaches `contextmenu`.

/**
 * How far down-right of the finger a long-press menu opens. The menu's first item would otherwise
 * sit exactly under the held finger, and the release (or the click some browsers synthesise from
 * it) could activate it. The menu clamps itself into the viewport, so near an edge it shifts back.
 */
export const TOUCH_MENU_OFFSET_PX = 24;

export interface PressEvent { pointerId: number; pointerType: string; clientX: number; clientY: number; type?: string }

export function createLongPress(
	onPress: (clientX: number, clientY: number) => void, holdMs = 500, slopPx = 10,
) {
	const down = new Set<number>();   // touch pointers currently on the screen
	let id = -1, x = 0, y = 0, x0 = 0, y0 = 0, timer: ReturnType<typeof setTimeout> | null = null;
	let fired = -1;                   // the pointer whose hold already opened a menu
	const stop = () => { if (timer !== null) { clearTimeout(timer); timer = null; } id = -1; };
	const isTouch = (ev: PressEvent) => ev.pointerType === 'touch';
	return {
		/** A pointerdown. Starts the hold timer for a lone touch; a second finger cancels it for good. */
		down(ev: PressEvent) {
			if (!isTouch(ev)) return;
			down.add(ev.pointerId);
			if (down.size > 1) { stop(); return; }   // a pan/pinch, not a hold (the timer only ever starts here)
			fired = -1;
			id = ev.pointerId; x = x0 = ev.clientX; y = y0 = ev.clientY;
			timer = setTimeout(() => { timer = null; fired = id; onPress(x, y); }, holdMs);
		},
		/** A pointermove: drifting past the slop turns the hold into a pan. Follows the finger inside the slop. */
		move(ev: PressEvent) {
			if (ev.pointerId !== id) return;
			if (Math.hypot(ev.clientX - x0, ev.clientY - y0) > slopPx) { stop(); return; }   // measured from where it landed, so a slow drift can't creep past
			x = ev.clientX; y = ev.clientY;   // the menu opens where the finger is now, not where it landed
		},
		/**
		 * A pointerup or pointercancel (`ev.type`). Cancels a pending hold. Returns true when this
		 * release ends a touch whose hold already fired, so the caller can skip any tap behaviour.
		 */
		up(ev: PressEvent): boolean {
			if (!isTouch(ev)) return false;
			down.delete(ev.pointerId);
			if (ev.pointerId === id) stop();
			const consumed = ev.pointerId === fired && ev.type !== 'pointercancel';
			if (ev.pointerId === fired) fired = -1;
			return consumed;
		},
		/** Whether a touch is on the screen: a `contextmenu` the browser raises for it is ours to swallow. */
		get touching(): boolean { return down.size > 0; },
		/** Drop everything (unmount, deactivate). */
		cancel() { down.clear(); stop(); fired = -1; },
	};
}
