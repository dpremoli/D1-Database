// Run: node --experimental-strip-types --test core/extensions/d1-ask-db/test/*.test.ts
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { csvCell, csvFilename, csvField, toCsv } from '../src/csv.ts';

test('csvCell: null, undefined, NaN and Infinity are empty', () => {
	for (const v of [null, undefined, NaN, Infinity, -Infinity, new Date('x')]) assert.equal(csvCell(v), '');
	assert.equal(csvCell(0), '0');
	assert.equal(csvCell(-1.5), '-1.5');
	assert.equal(csvCell(false), 'false');
	assert.equal(csvCell({ a: 1 }), '{"a":1}');
	assert.equal(csvCell(10n), '10');
});

test('csvField quotes only when needed and doubles quotes', () => {
	assert.equal(csvField('plain'), 'plain');
	assert.equal(csvField('a,b'), '"a,b"');
	assert.equal(csvField('say "hi"'), '"say ""hi"""');
	assert.equal(csvField('two\nlines'), '"two\nlines"');
	assert.equal(csvField('cr\rhere'), '"cr\rhere"');
});

test('toCsv: BOM, CRLF, header quoting, missing columns', () => {
	const out = toCsv(['code', 'note, x'], [{ code: 'S-1', 'note, x': 'a "b"' }, { code: null }, { code: NaN }]);
	assert.equal(out, '﻿code,"note, x"\r\nS-1,"a ""b"""\r\n,\r\n,\r\n');
});

test('toCsv: no rows still gives the header', () => {
	assert.equal(toCsv(['a', 'b'], []), '﻿a,b\r\n');
});

test('csvFilename: slug + date, accents stripped, capped, fallback', () => {
	const d = new Date('2026-10-05T12:00:00Z');
	assert.equal(csvFilename('Which samples weigh more than 50 grams?', d), 'ask-which-samples-weigh-more-than-50-grams-2026-10-05.csv');
	assert.equal(csvFilename('Café Ünïcode / test', d), 'ask-cafe-unicode-test-2026-10-05.csv');
	assert.equal(csvFilename('???', d), 'ask-answer-2026-10-05.csv');
	const long = csvFilename('a'.repeat(200), d);
	assert.ok(long.length <= 'ask-'.length + 50 + '-2026-10-05.csv'.length);
});
