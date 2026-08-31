import { describe, expect, it } from 'vitest';
import { D1AN_MAGIC, parseD1an } from './diagAttrs';

const NAME_BYTES = 16;
const HEADER_SIZE = 16;

function buildD1an(columns: Record<string, Float32Array>, opts?: { magic?: number; version?: number }): ArrayBuffer {
	const names = Object.keys(columns);
	const n = columns[names[0]]?.length ?? 0;
	const nCols = names.length;
	const buf = new ArrayBuffer(HEADER_SIZE + nCols * NAME_BYTES + nCols * n * 4);
	const dv = new DataView(buf);
	dv.setUint32(0, opts?.magic ?? D1AN_MAGIC, true);
	dv.setUint32(4, opts?.version ?? 1, true);
	dv.setUint32(8, n, true);
	dv.setUint32(12, nCols, true);
	let off = HEADER_SIZE;
	const enc = new TextEncoder();
	for (const name of names) {
		const bytes = new Uint8Array(buf, off, NAME_BYTES);
		bytes.set(enc.encode(name).subarray(0, NAME_BYTES));
		off += NAME_BYTES;
	}
	for (const name of names) {
		new Float32Array(buf, off, n).set(columns[name]);
		off += n * 4;
	}
	return buf;
}

describe('parseD1an', () => {
	it('round-trips named float32 columns', () => {
		const t = new Float32Array([0, 0.5, 1, 1.5]);
		const residZ = new Float32Array([-1.2, 0.3, 5.7, -0.9]);
		const buf = buildD1an({ t, resid_z: residZ });
		const parsed = parseD1an(buf);
		expect(parsed.n).toBe(4);
		expect(Array.from(parsed.columns.t)).toEqual(Array.from(t));
		expect(Array.from(parsed.columns.resid_z)).toEqual(Array.from(residZ));
	});

	it('rejects a bad magic number', () => {
		const buf = buildD1an({ t: new Float32Array([1, 2]) }, { magic: 0xdeadbeef });
		expect(() => parseD1an(buf)).toThrow(/magic/);
	});

	it('rejects an unsupported version', () => {
		const buf = buildD1an({ t: new Float32Array([1, 2]) }, { version: 2 });
		expect(() => parseD1an(buf)).toThrow(/version/);
	});

	it('handles a name shorter than the 16-byte slot (null-padded)', () => {
		const buf = buildD1an({ t: new Float32Array([1, 2, 3]) });
		const parsed = parseD1an(buf);
		expect(Object.keys(parsed.columns)).toEqual(['t']);
	});

	it('handles the full 16-byte name with no null terminator', () => {
		// 'tsa_resid_test16' is exactly 16 ASCII bytes -- the name field has no room for a
		// null terminator, which the parser must not require.
		const name = 'tsa_resid_test16';
		expect(name.length).toBe(16);
		const buf = buildD1an({ [name]: new Float32Array([9, 8, 7]) });
		const parsed = parseD1an(buf);
		expect(Object.keys(parsed.columns)).toEqual([name]);
		expect(Array.from(parsed.columns[name])).toEqual([9, 8, 7]);
	});
});
