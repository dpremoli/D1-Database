import { describe, expect, it } from 'vitest';
import { alignAndDiff } from './compare';

const SPR = 256;

// A repeatable "tool signature" waveform -- what a real cut's TSA signature would look like:
// a fundamental plus a harmonic, nothing random. Two passes sharing this exactly is the
// synthetic stand-in for "the tool/machine behaved the same both times".
function makeSignature(revs: Float32Array): Float32Array {
	const out = new Float32Array(revs.length);
	for (let i = 0; i < revs.length; i++) {
		out[i] = Math.sin(2 * Math.PI * revs[i]) + 0.5 * Math.sin(2 * Math.PI * 3 * revs[i]);
	}
	return out;
}

function revGrid(nRev: number, spr: number, offset = 0): Float32Array {
	const n = nRev * spr;
	const out = new Float32Array(n);
	for (let i = 0; i < n; i++) out[i] = offset + i / spr;
	return out;
}

describe('alignAndDiff', () => {
	it('recovers an anomaly present in only one pass, cancelling the shared tool signature', () => {
		// THE ground-truth test: two passes sharing the exact same repeatable waveform, one
		// with an extra anomaly the other never had. The diff must isolate that anomaly and
		// go quiet everywhere the two passes actually agreed.
		const revA = revGrid(20, SPR);
		const sigA = makeSignature(revA);
		const revB = revGrid(20, SPR);
		const sigB = makeSignature(revB);
		const hitIdx = Math.round(10 * SPR);
		sigB[hitIdx] += 5.0;

		const { rev, diff } = alignAndDiff(revA, sigA, revB, sigB, SPR);
		let peakIdx = 0;
		for (let i = 1; i < diff.length; i++) {
			if (Math.abs(diff[i]) > Math.abs(diff[peakIdx])) peakIdx = i;
		}
		expect(Math.abs(rev[peakIdx] - 10.0)).toBeLessThan(0.05);
		expect(Math.abs(diff[peakIdx])).toBeGreaterThan(4.0);
		// away from the anomaly, both passes agree -- the diff should be ~0
		const farIdx = Math.round(2 * SPR);
		expect(Math.abs(diff[farIdx])).toBeLessThan(0.01);
	});

	it('resamples only the overlapping revolution range when passes cover different spans', () => {
		const revA = revGrid(20, SPR, 0); // covers 0..20
		const revB = revGrid(20, SPR, 5); // covers 5..25
		const sigA = makeSignature(revA);
		const sigB = makeSignature(revB);
		const { rev } = alignAndDiff(revA, sigA, revB, sigB, SPR);
		expect(rev[0]).toBeCloseTo(5.0, 2);
		expect(rev[rev.length - 1]).toBeLessThanOrEqual(20.0 + 1e-6);
	});

	it('throws when the two revolution ranges do not overlap at all', () => {
		const revA = revGrid(5, SPR, 0); // 0..5
		const revB = revGrid(5, SPR, 10); // 10..15
		const sigA = makeSignature(revA);
		const sigB = makeSignature(revB);
		expect(() => alignAndDiff(revA, sigA, revB, sigB, SPR)).toThrow(/overlap/);
	});

	it('throws when a rev/sig pair has mismatched lengths', () => {
		const revA = revGrid(5, SPR);
		const sigA = new Float32Array(revA.length - 1);
		const revB = revGrid(5, SPR);
		const sigB = makeSignature(revB);
		expect(() => alignAndDiff(revA, sigA, revB, sigB, SPR)).toThrow(/length/);
	});
});
