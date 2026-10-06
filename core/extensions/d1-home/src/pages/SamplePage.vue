<script setup lang="ts">
import { computed, ref, toRef } from 'vue';
import {
	EditDrawer, LoadState, RecordHeader, RecordLink, Section, StatusBadge,
	buildLife, dataStudioRoute, truncatedNotes,
} from '@d1/ui';
import { useSampleData } from './sample/useSampleData';
import SampleOverview from './sample/SampleOverview.vue';
import LifeStrip from './sample/LifeStrip.vue';
import SampleRecords from './sample/SampleRecords.vue';
import SampleFiles from './sample/SampleFiles.vue';

// Sample page: everything about one physical sample on one screen, with every related record a
// link to its own page. Design: docs/superpowers/specs/2026-10-06-explorer-pages-design.md.
const props = defineProps<{ id: string }>();

const { sample, loading, notVisible, error, elements, campaigns, operations, tests, files, trace, reload } =
	useSampleData(toRef(props, 'id'));

const editing = ref(false);

const code = computed(() => sample.value?.sample_code ?? 'Sample');
const studioTo = computed(() => dataStudioRoute('physical_samples', props.id));
const life = computed(() => (trace.value.data ? buildLife(trace.value.data) : []));
const notes = computed(() => (trace.value.data ? truncatedNotes(trace.value.data) : []));
const campaignRows = computed(() => campaigns.value.data.map((c: any) => c.campaign_id).filter((c: any) => c?.campaign_id));

// /d1-report/* are endpoint pages (printable HTML), not app routes: open them in a new tab, same
// session, as the Home page does.
const openReport = (path: string) => window.open(path, '_blank', 'noopener');
const printLabel = () => openReport(`/d1-report/label?ids=${encodeURIComponent(props.id)}`);
const openReportPage = () => openReport(`/d1-report/sample/${encodeURIComponent(props.id)}`);
</script>

<template>
	<private-view :title="code">
		<div class="sample-page">
			<LoadState v-if="loading && !sample" loading loading-text="Loading sample…" />

			<div v-else-if="notVisible" class="not-found">
				<v-icon name="lock" large />
				<h2>Not found or not visible to you</h2>
				<p>This sample does not exist, or you do not have permission to see it.</p>
				<v-button to="/home">Back to Home</v-button>
			</div>

			<LoadState v-else-if="error" :error="error" />

			<template v-else-if="sample">
				<RecordHeader :code="code" :title="sample.nickname" kind="Sample" icon="science">
					<template #crumbs>
						<router-link to="/home">Home</router-link>
						<template v-if="sample.project_id">
							<span>›</span>
							<RecordLink collection="projects" :id="sample.project_id.project_id">
								{{ sample.project_id.project_code }}
							</RecordLink>
						</template>
						<template v-for="c in campaignRows" :key="c.campaign_id">
							<span>›</span>
							<RecordLink collection="campaigns" :id="c.campaign_id">{{ c.campaign_code || c.name || 'Campaign' }}</RecordLink>
						</template>
					</template>
					<template #status><StatusBadge kind="sample" :value="sample.current_status" /></template>
					<template #meta>
						<span v-if="sample.owner_person_id">Owner: {{ sample.owner_person_id.full_name }}</span>
						<span v-if="sample.co_owners">Co-owners: {{ sample.co_owners }}</span>
						<span v-if="sample.project_id?.project_name">{{ sample.project_id.project_name }}</span>
						<span v-if="sample.export_controlled" class="export">Export controlled</span>
					</template>
					<template #actions>
						<v-button small @click="editing = true"><v-icon name="edit" small left />Edit</v-button>
						<v-button small secondary @click="printLabel"><v-icon name="label" small left />Print label</v-button>
						<v-button small secondary @click="openReportPage"><v-icon name="picture_as_pdf" small left />Report</v-button>
						<v-button small secondary :to="studioTo"><v-icon name="open_in_new" small left />Data Studio</v-button>
					</template>
				</RecordHeader>

				<Section title="Overview">
					<SampleOverview
						:sample="sample"
						:elements="elements.data"
						:elements-loading="elements.loading"
						:elements-error="elements.error"
					/>
				</Section>

				<Section title="Life of the sample">
					<LoadState :loading="trace.loading" :error="trace.error">
						<LifeStrip :items="life" />
						<p v-for="n in notes" :key="n" class="note">{{ n }}</p>
					</LoadState>
				</Section>

				<SampleRecords :operations="operations" :tests="tests" />
				<SampleFiles :files="files.data" :loading="files.loading" :error="files.error" />

				<EditDrawer
					v-model="editing"
					collection="physical_samples"
					:primary-key="id"
					:title="`Edit ${code}`"
					@saved="reload()"
				/>
			</template>
		</div>
	</private-view>
</template>

<style scoped>
.sample-page {
	max-width: 1180px;
	margin: 0 auto;
	padding: 24px 32px 64px;
	font-family: var(--theme--fonts--sans--font-family, -apple-system, 'Segoe UI', Roboto, sans-serif);
	color: var(--theme--foreground);
}
.sample-page :deep(.crumbs a) { color: var(--theme--primary); text-decoration: none; font-weight: 600; }
.sample-page :deep(.crumbs a:hover) { text-decoration: underline; }
.export { color: var(--theme--danger); font-weight: 650; }
.note { margin: 8px 0 0; font-size: 12.5px; color: var(--theme--warning); }
.not-found {
	max-width: 520px;
	margin: 64px auto;
	text-align: center;
	display: flex;
	flex-direction: column;
	align-items: center;
	gap: 10px;
}
.not-found :deep(.v-icon) { --v-icon-color: var(--theme--foreground-subdued); }
.not-found h2 { margin: 6px 0 0; font-size: 20px; }
.not-found p { margin: 0 0 12px; color: var(--theme--foreground-subdued); }
</style>
