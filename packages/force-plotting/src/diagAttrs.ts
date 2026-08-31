// D1AN analysis-attribute binary reader -- the browser-side mirror of scripts/diag/d1an.py.
// Byte layout is fixed by that file; this must match it exactly:
//   magic u32 | version u32 | n u32 | n_cols u32
//   n_cols * 16-byte ASCII column names (null-padded, or exactly 16 bytes with no terminator)
//   n_cols * float32[n], column-major
//
// Published by the diag orchestrator handler alongside the octree files (see
// scripts/force_orchestrator.py's process_diag_row) at
// <octreeUrl>/diag/<operationId>/attrs.d1an -- this is the WorkingSet's data source for
// JS-side statistics (Selection Inspector, spatial predicates). Per-point GPU rendering reads
// the SAME underlying values a different way: as LAS extra-dim attributes streamed by the
// Potree octree itself (see DiagOctreeView.vue), not by fetching this file.

export const D1AN_MAGIC = 0x4431414e; // 'D1AN'
const D1AN_VERSION = 1;
const HEADER_SIZE = 16; // 4 * u32
const NAME_BYTES = 16;

export interface DiagAttrs {
	n: number;
	columns: Record<string, Float32Array>;
}

export function parseD1an(buf: ArrayBuffer): DiagAttrs {
	if (buf.byteLength < HEADER_SIZE) throw new Error('D1AN buffer too short for header');
	const dv = new DataView(buf);
	const magic = dv.getUint32(0, true);
	if (magic !== D1AN_MAGIC) {
		throw new Error(`bad D1AN magic 0x${magic.toString(16)}`);
	}
	const version = dv.getUint32(4, true);
	if (version !== D1AN_VERSION) {
		throw new Error(`unsupported D1AN version ${version}`);
	}
	const n = dv.getUint32(8, true);
	const nCols = dv.getUint32(12, true);

	const decoder = new TextDecoder('ascii');
	const names: string[] = [];
	let off = HEADER_SIZE;
	for (let i = 0; i < nCols; i++) {
		const bytes = new Uint8Array(buf, off, NAME_BYTES);
		const nul = bytes.indexOf(0);
		names.push(decoder.decode(bytes.subarray(0, nul < 0 ? NAME_BYTES : nul)));
		off += NAME_BYTES;
	}

	// off is now HEADER_SIZE + nCols*NAME_BYTES, always a multiple of 4 (both terms are
	// multiples of 4), so each column below can be a zero-copy Float32Array view rather than
	// a copy -- important at multi-million-point sizes.
	const columns: Record<string, Float32Array> = {};
	const bytesNeeded = off + nCols * n * 4;
	if (buf.byteLength < bytesNeeded) {
		throw new Error(
			`D1AN buffer truncated: need ${bytesNeeded} bytes, have ${buf.byteLength}`,
		);
	}
	for (let i = 0; i < nCols; i++) {
		columns[names[i]] = new Float32Array(buf, off, n);
		off += n * 4;
	}
	return { n, columns };
}

export async function fetchD1an(url: string): Promise<DiagAttrs> {
	const res = await fetch(url, { cache: 'no-store' });
	if (!res.ok) throw new Error(`D1AN fetch failed: ${res.status} ${res.statusText}`);
	return parseD1an(await res.arrayBuffer());
}
