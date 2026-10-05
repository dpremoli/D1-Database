import { describe, expect, it } from 'vitest';
import { toCsv, safeFilePart, type CsvColumn } from './csvExport';

interface R { a: string | number | null | undefined; b?: number }
const cols: CsvColumn<R>[] = [
	{ header: 'a_N', value: (r) => r.a },
	{ header: 'b_mm', value: (r) => r.b },
];

describe('toCsv', () => {
	it('writes headers in column order, CRLF-terminated', () => {
		expect(toCsv(cols, [{ a: 1, b: 2 }, { a: 3, b: 4 }])).toBe('a_N,b_mm\r\n1,2\r\n3,4\r\n');
	});
	it('emits only the header for no rows', () => {
		expect(toCsv(cols, [])).toBe('a_N,b_mm\r\n');
	});
	it('quotes commas, quotes and newlines (RFC 4180)', () => {
		const csv = toCsv(cols, [{ a: 'x,y' }, { a: 'say "hi"' }, { a: 'l1\nl2' }, { a: 'cr\rx' }]);
		expect(csv).toBe('a_N,b_mm\r\n"x,y",\r\n"say ""hi""",\r\n"l1\nl2",\r\n"cr\rx",\r\n');
	});
	it('exports NaN, infinities, null and undefined as empty cells but keeps 0', () => {
		const csv = toCsv(cols, [{ a: NaN, b: Infinity }, { a: null, b: undefined }, { a: 0, b: -0.5 }]);
		expect(csv).toBe('a_N,b_mm\r\n,\r\n,\r\n0,-0.5\r\n');
	});
	it('quotes header cells too', () => {
		expect(toCsv([{ header: 'a,b', value: () => 1 }], [{ a: 1 }])).toBe('"a,b"\r\n1\r\n');
	});
});

describe('safeFilePart', () => {
	it('replaces unsafe runs and trims', () => {
		expect(safeFilePart(' Op/12 A ')).toBe('Op_12_A');
		expect(safeFilePart(null)).toBe('');
	});
});
