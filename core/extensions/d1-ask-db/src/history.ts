/**
 * Per-browser question history and saved questions, kept in localStorage.
 *
 * Only the question text and a timestamp are stored, never result rows. Every storage access is
 * wrapped in try/catch: private windows and blocked site data make localStorage throw.
 */
export interface StoredQuestion {
	question: string;
	/** Epoch milliseconds when it was asked or saved. */
	at: number;
}

export const HISTORY_KEY = 'd1-ask-db:history';
export const SAVED_KEY = 'd1-ask-db:saved';
/** History keeps the newest N questions; the saved list is never trimmed. */
export const HISTORY_LIMIT = 20;

const norm = (q: string) => q.trim().replace(/\s+/g, ' ').toLowerCase();

/** Newest first, one entry per question (case and spacing ignored), cut to `limit` if given. */
export function addQuestion(
	list: StoredQuestion[],
	question: string,
	now: number,
	limit?: number,
): StoredQuestion[] {
	const text = question.trim();
	if (!text) return list;
	const key = norm(text);
	const next = [{ question: text, at: now }, ...list.filter((e) => norm(e.question) !== key)];
	return limit === undefined ? next : next.slice(0, limit);
}

export function removeQuestion(list: StoredQuestion[], question: string): StoredQuestion[] {
	const key = norm(question);
	return list.filter((e) => norm(e.question) !== key);
}

export function hasQuestion(list: StoredQuestion[], question: string): boolean {
	const key = norm(question);
	return list.some((e) => norm(e.question) === key);
}

/** Parse stored JSON defensively: anything malformed is dropped rather than thrown. */
export function parseStored(raw: string | null): StoredQuestion[] {
	if (!raw) return [];
	try {
		const data = JSON.parse(raw);
		if (!Array.isArray(data)) return [];
		return data
			.filter((e) => e && typeof e.question === 'string' && e.question.trim())
			.map((e) => ({ question: e.question as string, at: Number.isFinite(e.at) ? (e.at as number) : 0 }));
	} catch {
		return [];
	}
}

export function loadList(key: string): StoredQuestion[] {
	try {
		return parseStored(window.localStorage.getItem(key));
	} catch {
		return [];
	}
}

/** Best effort: a full or unavailable store just means the list lasts until the page closes. */
export function saveList(key: string, list: StoredQuestion[]): void {
	try {
		window.localStorage.setItem(key, JSON.stringify(list));
	} catch {
		// ignore
	}
}
