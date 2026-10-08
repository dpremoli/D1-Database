import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { onCanvasRevival } from './canvasRevival';

// Node's EventTarget stands in for the canvas, document and window (no DOM in this environment).
function rig() {
	const canvas = new EventTarget(), win = new EventTarget();
	const doc = Object.assign(new EventTarget(), { hidden: true });
	const repaint = vi.fn();
	const off = onCanvasRevival(canvas, doc, win, repaint);
	return { canvas, doc, win, repaint, off };
}

describe('onCanvasRevival (#189)', () => {
	it('repaints when the canvas context is restored', () => {
		const r = rig();
		r.canvas.dispatchEvent(new Event('contextrestored'));
		expect(r.repaint).toHaveBeenCalledTimes(1);
	});
	it('cancels contextlost so the browser may restore it', () => {
		const r = rig();
		const ev = new Event('contextlost', { cancelable: true });
		r.canvas.dispatchEvent(ev);
		expect(ev.defaultPrevented).toBe(true);
		expect(r.repaint).not.toHaveBeenCalled();
	});
	it('repaints when the document becomes visible, not when it hides', () => {
		const r = rig();
		r.doc.dispatchEvent(new Event('visibilitychange'));
		expect(r.repaint).not.toHaveBeenCalled();
		r.doc.hidden = false;
		r.doc.dispatchEvent(new Event('visibilitychange'));
		expect(r.repaint).toHaveBeenCalledTimes(1);
	});
	it('repaints when the window regains focus', () => {
		const r = rig();
		r.win.dispatchEvent(new Event('focus'));
		expect(r.repaint).toHaveBeenCalledTimes(1);
	});
	it('removes every listener on cleanup', () => {
		const r = rig();
		r.off();
		r.canvas.dispatchEvent(new Event('contextrestored'));
		r.doc.hidden = false;
		r.doc.dispatchEvent(new Event('visibilitychange'));
		r.win.dispatchEvent(new Event('focus'));
		expect(r.repaint).not.toHaveBeenCalled();
	});
});

// The components can't be mounted here (no DOM), so check that both plots use the helper and
// release it on unmount.
describe('plots wire up onCanvasRevival (#189)', () => {
	for (const f of ['./LiveForcePlot.vue', './FinishedForcePlot.vue']) {
		it(f, () => {
			const src = readFileSync(fileURLToPath(new URL(f, import.meta.url)), 'utf8');
			expect(src).toMatch(/onCanvasRevival\(\s*canvasEl\.value,\s*document,\s*window,\s*resize\s*\)/);
			expect(src).toMatch(/stopRevival\?\.\(\)/);
		});
	}
});
