// @d1/ui: the shared kit of the Explorer pages. Pure logic first (all unit-tested), then the
// components, which use Directus theme variables and the app's global components only.

export { recordRoute, collectionRoute, dataStudioRoute } from './recordRoute';
export { statusStyle, humanise, TEST_STATUS, FORCE_STATUS, DIAG_STATUS, SAMPLE_STATUS } from './status';
export type { StatusKind, StatusStyle, Tone } from './status';
export { processLabel, analysisLink, PROCESS_LABEL } from './process';
export type { AnalysisLink } from './process';
export { formatDate, formatNumber, errorText, isNotVisible } from './format';
export { buildComposition, toElements, compositionAria } from './composition';
export type { ElementRow, Segment, Composition } from './composition';
export { linkedFiles, DEFAULT_UNC_PREFIX } from './linkedFiles';
export type { LinkedFile } from './linkedFiles';
export { buildLife, truncatedNotes, hiddenText } from './life';
export type { LifeItem, LifeKind, TraceResponse } from './life';

export { useItems } from './composables/useItems';
export { useRequestGate } from './composables/useRequestGate';

export { default as RecordHeader } from './components/RecordHeader.vue';
export { default as StatTile } from './components/StatTile.vue';
export { default as StatusBadge } from './components/StatusBadge.vue';
export { default as RecordLink } from './components/RecordLink.vue';
export { default as Section } from './components/Section.vue';
export { default as LoadState } from './components/LoadState.vue';
export { default as KeyValueGrid } from './components/KeyValueGrid.vue';
export type { KeyValue } from './components/KeyValueGrid.vue';
export { default as ProgressBar } from './components/ProgressBar.vue';
export { default as CompositionBar } from './components/CompositionBar.vue';
