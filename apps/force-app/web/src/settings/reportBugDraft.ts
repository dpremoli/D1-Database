// #42: the report-a-bug form used to keep its draft in ReportBugSettings.vue's own component-local
// refs, so switching Settings tabs (or popping the window out) — either of which unmounts that
// component — silently wiped whatever the operator had already typed. Module-level state (the same
// pattern router.ts uses for lastNonSettingsRoute) survives remounts; only a successful submit
// clears it.
import { ref } from 'vue';

export const draftKind = ref<'bug' | 'feature'>('bug');
export const draftArea = ref<string>('general');
export const draftTitle = ref('');
export const draftDescription = ref('');
export const draftIncludeLogs = ref(true);

export function resetDraft(): void {
	draftKind.value = 'bug';
	draftTitle.value = '';
	draftDescription.value = '';
	draftIncludeLogs.value = true;
	// area intentionally left as-is: the next report is more likely to be filed from a similar
	// place than to want a fresh route-based guess right after submitting one.
}
