import { beforeEach, describe, expect, it, vi } from 'vitest';
import { D1AN_MAGIC } from './diagAttrs';
import { fetchDiagPreview } from './diagPreview';
import { DEFAULT_RECIPE } from './recipeChannels';
import { resetForceHost, setForceHost, type ForceHost } from './host';

const HEADER_SIZE = 16;
const NAME_BYTES = 16;

function buildD1an(columns: Record<string, Float32Array>): ArrayBuffer {
	const names = Object.keys(columns);
	const n = columns[names[0]]?.length ?? 0;
	const nCols = names.length;
	const buf = new ArrayBuffer(HEADER_SIZE + nCols * NAME_BYTES + nCols * n * 4);
	const dv = new DataView(buf);
	dv.setUint32(0, D1AN_MAGIC, true);
	dv.setUint32(4, 1, true);
	dv.setUint32(8, n, true);
	dv.setUint32(12, nCols, true);
	let off = HEADER_SIZE;
	const enc = new TextEncoder();
	for (const name of names) {
		new Uint8Array(buf, off, NAME_BYTES).set(enc.encode(name).subarray(0, NAME_BYTES));
		off += NAME_BYTES;
	}
	for (const name of names) {
		new Float32Array(buf, off, n).set(columns[name]);
		off += n * 4;
	}
	return buf;
}

beforeEach(() => {
	resetForceHost();
	setForceHost({
		diagUrl: '/diag',
		fetchCredentials: 'omit',
		authHeaders: () => ({}),
	} as ForceHost);
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: true,
			arrayBuffer: async () => buildD1an({ x: new Float32Array([0]), y: new Float32Array([0]) }),
			headers: new Headers({ 'X-Diag-Ms': '12', 'X-Diag-Cache': 'miss' }),
		}),
	);
});

describe('fetchDiagPreview', () => {
	it('omits stop_after (sends null) when the caller does not pass one', async () => {
		await fetchDiagPreview('a1', DEFAULT_RECIPE, null);
		const opt = (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls[0][1] as { body: string };
		const body = JSON.parse(opt.body);
		expect(body.stop_after).toBeNull();
	});

	it('sends the requested stop_after index, for "revert view to this step"', async () => {
		await fetchDiagPreview('a1', DEFAULT_RECIPE, null, undefined, undefined, 3);
		const opt = (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls[0][1] as { body: string };
		const body = JSON.parse(opt.body);
		expect(body.stop_after).toBe(3);
	});
});
