// How a typeahead list shows items that are already chosen (#99). One rule everywhere:
//  - a multi-pick list (picks accumulate as chips, e.g. LabAmp's previous recordings) HIDES what
//    is already picked -- offering it again only invites a duplicate;
//  - a single-value field (LookupField, CutPicker) MARKS its current value with a check and
//    aria-selected, and still lets it be picked again.
// Items in `selectedIds` that are not hidden stay visible but disabled ("already added"), and
// keyboard navigation skips them (listNav.ts).
export interface PickRow<T> {
	item: T;
	/** The field's current value. */
	current: boolean;
	/** Already picked into a multi-pick selection. */
	picked: boolean;
	/** Not pickable (picked, but shown because hideSelected is off). */
	disabled: boolean;
}

export interface PickOptions {
	currentId?: string | null;
	selectedIds?: readonly string[] | null;
	hideSelected?: boolean;
}

export function pickRows<T>(items: readonly T[], idOf: (item: T) => string, opts: PickOptions = {}): PickRow<T>[] {
	const selected = new Set(opts.selectedIds ?? []);
	const rows: PickRow<T>[] = [];
	for (const item of items) {
		const id = idOf(item);
		const picked = selected.has(id);
		if (picked && opts.hideSelected) continue;
		rows.push({ item, current: !!opts.currentId && id === opts.currentId, picked, disabled: picked });
	}
	return rows;
}
