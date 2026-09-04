import { beforeEach, describe, expect, it, vi } from 'vitest';
import { D1AN_MAGIC } from './diagAttrs';
import { fetchViewportCompute } from './diagViewport';
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
			arrayBuffer: async () =>
				buildD1an({
					x: new Float32Array([0, 1]),
					y: new Float32Array([10, 11]),
					value: new Float32Array([20, 21]),
				}),
			headers: new Headers({ 'X-Diag-Ms': '42', 'X-Diag-Viewport-N': '2' }),
		}),
	);
});

describe('fetchViewportCompute', () => {
	it('POSTs bbox + step and parses the D1AN response', async () => {
		const res = await fetchViewportCompute('a1', [0, 0, 10, 10], {
			op: 'getis_ord',
			params: { k: 30 },
		});
		expect(res.n).toBe(2);
		expect(res.op).toBe('getis_ord');
		expect(Array.from(res.x)).toEqual([0, 1]);
		expect(Array.from(res.value)).toEqual([20, 21]);
		expect(res.ms).toBe(42);
		const call = (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls[0];
		expect(call[0]).toBe('/diag/viewport');
		const body = JSON.parse((call[1] as { body: string }).body);
		expect(body.bbox).toEqual([0, 0, 10, 10]);
		expect(body.step.op).toBe('getis_ord');
		expect(body.max_points).toBe(1_000_000);
	});

	it('forwards layers and maxPoints when supplied', async () => {
		await fetchViewportCompute('a1', [-5, -5, 5, 5], { op: 'hdbscan', params: {} }, {
			layers: { L: { role: 'seed' } },
			maxPoints: 5000,
		});
		const opt = (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls[0][1] as {
			body: string;
		};
		const body = JSON.parse(opt.body);
		expect(body.layers).toEqual({ L: { role: 'seed' } });
		expect(body.max_points).toBe(5000);
	});

	it('throws a message an analyst can act on, keeping the raw body off the panel', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn().mockResolvedValue({
				ok: false,
				status: 422,
				text: async () => JSON.stringify({ detail: 'empty viewport' }),
			}),
		);
		await expect(
			fetchViewportCompute('a1', [0, 0, 1, 1], { op: 'getis_ord', params: {} }),
		).rejects.toMatchObject({
			// Neither the status code nor JSON braces may reach the message — that shape was
			// the reported `diag preview: 401 {"detail":"not permitted"}` defect.
			message: "This recipe can't run: empty viewport",
			status: 422,
			detail: expect.stringContaining('empty viewport'),
		});
	});
});
