// Run: node --experimental-strip-types --test core/extensions/d1-ask-db/test/*.test.ts
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
	HISTORY_LIMIT,
	addQuestion,
	hasQuestion,
	loadList,
	parseStored,
	removeQuestion,
	saveList,
} from '../src/history.ts';

test('addQuestion: newest first, deduplicated ignoring case and spacing', () => {
	let l = addQuestion([], 'How many samples?', 1);
	l = addQuestion(l, 'Which tests?', 2);
	l = addQuestion(l, '  how   many SAMPLES? ', 3);
	assert.deepEqual(l, [
		{ question: 'how   many SAMPLES?', at: 3 },
		{ question: 'Which tests?', at: 2 },
	]);
});

test('addQuestion: blank is ignored; limit trims the oldest', () => {
	assert.deepEqual(addQuestion([], '   ', 1), []);
	let l: ReturnType<typeof addQuestion> = [];
	for (let i = 0; i < HISTORY_LIMIT + 5; i++) l = addQuestion(l, `q${i}`, i, HISTORY_LIMIT);
	assert.equal(l.length, HISTORY_LIMIT);
	assert.equal(l[0].question, `q${HISTORY_LIMIT + 4}`);
	assert.equal(l.at(-1)!.question, 'q5');
});

test('addQuestion without a limit never trims (saved list)', () => {
	let l: ReturnType<typeof addQuestion> = [];
	for (let i = 0; i < 50; i++) l = addQuestion(l, `q${i}`, i);
	assert.equal(l.length, 50);
});

test('removeQuestion / hasQuestion', () => {
	const l = addQuestion(addQuestion([], 'a', 1), 'b', 2);
	assert.equal(hasQuestion(l, ' A '), true);
	assert.deepEqual(removeQuestion(l, 'A').map((e) => e.question), ['b']);
});

test('parseStored drops malformed data instead of throwing', () => {
	assert.deepEqual(parseStored(null), []);
	assert.deepEqual(parseStored('{not json'), []);
	assert.deepEqual(parseStored('{"a":1}'), []);
	assert.deepEqual(parseStored('[null, 3, {"question":""}, {"question":"ok","at":"x"}, {"question":"fine","at":5}]'), [
		{ question: 'ok', at: 0 },
		{ question: 'fine', at: 5 },
	]);
});

test('loadList / saveList survive a localStorage that throws', () => {
	const g = globalThis as any;
	g.window = {
		localStorage: {
			getItem() {
				throw new Error('denied');
			},
			setItem() {
				throw new Error('denied');
			},
		},
	};
	assert.deepEqual(loadList('k'), []);
	assert.doesNotThrow(() => saveList('k', [{ question: 'q', at: 1 }]));
	const store = new Map<string, string>();
	g.window = { localStorage: { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => store.set(k, v) } };
	saveList('k', [{ question: 'q', at: 1 }]);
	assert.deepEqual(loadList('k'), [{ question: 'q', at: 1 }]);
	delete g.window;
});
