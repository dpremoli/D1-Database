// Release notes by category (#137). A changelog entry's `notes` stay a flat string[] -- the release
// job reads them with a regex (.github/scripts/release_plan.py), so they can't become objects --
// and the category is the note's leading prefix:
//
//   "Fixed: ..."     -> Fixed
//   "Security: ..."  -> Fixed (the prefix stays: it is the point of the note)
//   "Improved: ..."  -> Improved
//   "New: ..." or no prefix -> New
//
// release_plan.py groups the GitHub Release notes the same way; keep the two in step.

export type NoteGroupKey = 'new' | 'improved' | 'fixed';

export interface NoteGroup {
	key: NoteGroupKey;
	/** Sub-heading shown above the notes. */
	label: string;
	notes: string[];
}

/** The prefixes a note may start with. Anything else before a colon is just part of the sentence
 *  ("Plot page: ..."), and the note counts as New. */
export const NOTE_PREFIXES: Record<string, { group: NoteGroupKey; strip: boolean }> = {
	New: { group: 'new', strip: true },
	Improved: { group: 'improved', strip: true },
	Fixed: { group: 'fixed', strip: true },
	Security: { group: 'fixed', strip: false },
};

const GROUPS: { key: NoteGroupKey; label: string }[] = [
	{ key: 'new', label: 'New' },
	{ key: 'improved', label: 'Improved' },
	{ key: 'fixed', label: 'Fixed' },
];

const PREFIX_RE = /^([A-Za-z]+):\s+/;

/** Which group a note belongs to, and the text to show for it (prefix removed where it is only a label). */
export function classifyNote(note: string): { group: NoteGroupKey; text: string } {
	const m = PREFIX_RE.exec(note);
	if (m && Object.hasOwn(NOTE_PREFIXES, m[1])) {
		const p = NOTE_PREFIXES[m[1]];
		return { group: p.group, text: p.strip ? note.slice(m[0].length) : note };
	}
	return { group: 'new', text: note };
}

/** The notes split into New / Improved / Fixed, in that order, leaving out empty groups. Each
 *  group keeps the notes' original order. */
export function groupNotes(notes: readonly string[]): NoteGroup[] {
	const out: NoteGroup[] = GROUPS.map((g) => ({ ...g, notes: [] }));
	for (const n of notes) {
		const { group, text } = classifyNote(n);
		out.find((g) => g.key === group)!.notes.push(text);
	}
	return out.filter((g) => g.notes.length > 0);
}
