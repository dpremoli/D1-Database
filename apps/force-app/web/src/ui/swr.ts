// Stale-while-revalidate for a page's server state (#109). Held at module level by the caller, so
// it outlives the page component: reopening the page shows the last-known data at once and
// refreshes it in the background, instead of an empty "no data" state that repopulates a moment
// later.
//
// A refresh that started before a local change must not overwrite it. `mutate` is how the page
// writes a server response it already has (a save returning the new rows) and it also bumps an
// epoch, so a revalidation that was in flight across that write drops its now-stale result.
import { ref, shallowRef, type Ref, type ShallowRef } from 'vue';

export interface Swr<T> {
	/** Last-known data; null until the first load succeeds. */
	data: ShallowRef<T | null>;
	/** A load is in flight (first or background). */
	loading: Ref<boolean>;
	/** Message from the latest failed load; cleared by the next success. */
	error: Ref<string | null>;
	/** Refetch. Concurrent calls share the one in-flight request. */
	revalidate(): Promise<void>;
	/** Replace the data locally (e.g. with a save's response) and invalidate in-flight loads. */
	mutate(next: T | ((cur: T | null) => T)): void;
}

export function createSwr<T>(load: () => Promise<T>): Swr<T> {
	const data = shallowRef<T | null>(null);
	const loading = ref(false);
	const error = ref<string | null>(null);
	let inflight: Promise<void> | null = null;
	let epoch = 0;

	function revalidate(): Promise<void> {
		if (inflight) return inflight;
		const started = epoch;
		loading.value = true;
		inflight = (async () => {
			try {
				const next = await load();
				if (started === epoch) { data.value = next; error.value = null; }
			} catch (e: any) {
				// Keep showing the last-known data; the page shows the error beside it.
				error.value = e?.message || String(e);
			} finally {
				loading.value = false;
				inflight = null;
			}
		})();
		return inflight;
	}

	function mutate(next: T | ((cur: T | null) => T)) {
		epoch++;
		data.value = typeof next === 'function' ? (next as (cur: T | null) => T)(data.value) : next;
	}

	return { data, loading, error, revalidate, mutate };
}
