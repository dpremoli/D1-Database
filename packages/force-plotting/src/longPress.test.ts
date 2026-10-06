import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createLongPress, type PressEvent } from './longPress';

const touch = (id: number, x: number, y: number, type?: string): PressEvent => ({ pointerId: id, pointerType: 'touch', clientX: x, clientY: y, type });

describe('createLongPress', () => {
	beforeEach(() => { vi.useFakeTimers(); });
	afterEach(() => { vi.useRealTimers(); });

	it('fires once with the client point after the hold, and the release is consumed', () => {
		const got: [number, number][] = [];
		const lp = createLongPress((x, y) => got.push([x, y]));
		lp.down(touch(1, 100, 200));
		vi.advanceTimersByTime(499);
		expect(got).toEqual([]);
		vi.advanceTimersByTime(1);
		expect(got).toEqual([[100, 200]]);
		vi.advanceTimersByTime(5000);
		expect(got).toHaveLength(1);
		expect(lp.up(touch(1, 100, 200, 'pointerup'))).toBe(true);
		expect(lp.up(touch(1, 100, 200, 'pointerup'))).toBe(false);   // only the one release
	});
	it('a release before the hold cancels it and is not consumed', () => {
		const onPress = vi.fn();
		const lp = createLongPress(onPress);
		lp.down(touch(1, 10, 10));
		vi.advanceTimersByTime(300);
		expect(lp.up(touch(1, 10, 10, 'pointerup'))).toBe(false);
		vi.advanceTimersByTime(1000);
		expect(onPress).not.toHaveBeenCalled();
	});
	it('movement within the slop keeps it, and the menu opens at the finger\'s latest point', () => {
		const got: [number, number][] = [];
		const lp = createLongPress((x, y) => got.push([x, y]));
		lp.down(touch(1, 100, 100));
		lp.move(touch(1, 104, 103));
		vi.advanceTimersByTime(500);
		expect(got).toEqual([[104, 103]]);
	});
	it('movement beyond the slop cancels it (a pan)', () => {
		const onPress = vi.fn();
		const lp = createLongPress(onPress);
		lp.down(touch(1, 100, 100));
		lp.move(touch(1, 100, 111));
		vi.advanceTimersByTime(2000);
		expect(onPress).not.toHaveBeenCalled();
	});
	it('a slow drift that adds up past the slop cancels it too', () => {
		const onPress = vi.fn();
		const lp = createLongPress(onPress);
		lp.down(touch(1, 100, 100));
		for (let k = 1; k <= 8; k++) lp.move(touch(1, 100 + k * 2, 100));   // 2 px per move, 16 px in all
		vi.advanceTimersByTime(2000);
		expect(onPress).not.toHaveBeenCalled();
	});
	it('a second finger cancels it, and stays cancelled when the second lifts', () => {
		const onPress = vi.fn();
		const lp = createLongPress(onPress);
		lp.down(touch(1, 100, 100));
		vi.advanceTimersByTime(200);
		lp.down(touch(2, 150, 100));
		lp.up(touch(2, 150, 100, 'pointerup'));
		vi.advanceTimersByTime(2000);
		expect(onPress).not.toHaveBeenCalled();
	});
	it('pointercancel cancels it and is not consumed', () => {
		const onPress = vi.fn();
		const lp = createLongPress(onPress);
		lp.down(touch(1, 5, 5));
		expect(lp.up(touch(1, 5, 5, 'pointercancel'))).toBe(false);
		vi.advanceTimersByTime(1000);
		expect(onPress).not.toHaveBeenCalled();
	});
	it('a pointercancel after it fired is not a consumed release, but clears the state', () => {
		const lp = createLongPress(() => {});
		lp.down(touch(1, 5, 5));
		vi.advanceTimersByTime(500);
		expect(lp.up(touch(1, 5, 5, 'pointercancel'))).toBe(false);
		expect(lp.up(touch(1, 5, 5, 'pointerup'))).toBe(false);
	});
	it('ignores mouse and pen', () => {
		const onPress = vi.fn();
		const lp = createLongPress(onPress);
		lp.down({ pointerId: 1, pointerType: 'mouse', clientX: 0, clientY: 0 });
		lp.down({ pointerId: 2, pointerType: 'pen', clientX: 0, clientY: 0 });
		vi.advanceTimersByTime(2000);
		expect(onPress).not.toHaveBeenCalled();
		expect(lp.touching).toBe(false);
		expect(lp.up({ pointerId: 1, pointerType: 'mouse', clientX: 0, clientY: 0, type: 'pointerup' })).toBe(false);
	});
	it('arms again for the next touch after a fired one', () => {
		const onPress = vi.fn();
		const lp = createLongPress(onPress);
		lp.down(touch(1, 1, 1)); vi.advanceTimersByTime(500); lp.up(touch(1, 1, 1, 'pointerup'));
		lp.down(touch(2, 2, 2)); vi.advanceTimersByTime(500);
		expect(onPress).toHaveBeenCalledTimes(2);
		expect(onPress).toHaveBeenLastCalledWith(2, 2);
	});
	it('reports a touch on the screen, and cancel() drops a pending hold', () => {
		const onPress = vi.fn();
		const lp = createLongPress(onPress);
		expect(lp.touching).toBe(false);
		lp.down(touch(1, 1, 1));
		expect(lp.touching).toBe(true);
		lp.cancel();
		expect(lp.touching).toBe(false);
		vi.advanceTimersByTime(1000);
		expect(onPress).not.toHaveBeenCalled();
	});
});
