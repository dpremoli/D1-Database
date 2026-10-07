import { DEFAULT_WEEKS, windowStart } from '@d1/ui';

// Reads the dates of the operations and tests inside the sparkline window, for one project or for
// every project at once. Why a capped client fetch and not `aggregate` + `groupBy`: see the top of
// packages/d1-ui/src/activity.ts (TIMESTAMPTZ columns, and SQL year()/week() disagree at the
// turn of the year). Only two small columns come back per row, newest first, so a cap of
// ACTIVITY_ROW_CAP per collection covers a very busy lab (26 weeks x ~190 a week). Past the cap
// the oldest rows are the ones missing, and `truncated` lets the page say so.

export const ACTIVITY_ROW_CAP = 5000;

type GetItems = (collection: string, params?: Record<string, unknown>) => Promise<any[]>;

export interface ActivityRows {
	ops: { project_id: string; operation_date: string }[];
	tests: { project_id: string; session_date: string }[];
	truncated: boolean;
}

export async function fetchActivityRows(
	getItems: GetItems,
	projectId?: string,
	weeks: number = DEFAULT_WEEKS,
	now: Date = new Date(),
): Promise<ActivityRows> {
	const since = windowStart(weeks, now);
	const scope = projectId ? { project_id: { _eq: projectId } } : { project_id: { _nnull: true } };
	const read = (collection: string, dateField: string) =>
		getItems(collection, {
			filter: { _and: [scope, { [dateField]: { _gte: since } }] },
			fields: ['project_id', dateField],
			sort: [`-${dateField}`],
			limit: ACTIVITY_ROW_CAP,
		});
	const [ops, tests] = await Promise.all([
		read('manufacturing_operations', 'operation_date'),
		read('test_sessions', 'session_date'),
	]);
	return { ops, tests, truncated: ops.length >= ACTIVITY_ROW_CAP || tests.length >= ACTIVITY_ROW_CAP };
}
