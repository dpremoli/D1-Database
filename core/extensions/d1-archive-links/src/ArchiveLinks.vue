<template>
	<div class="d1-archive-links">
		<v-notice v-if="!hasKey" type="info">Save the item to see its linked files here.</v-notice>
		<v-progress-circular v-else-if="loading" indeterminate small />
		<v-notice v-else-if="!rows.length" type="info">
			No files linked yet — attach some via the “Linked Data Files” field above.
		</v-notice>
		<template v-else>
			<div class="list">
				<div v-for="row in rows" :key="row.id" class="row">
					<v-icon name="insert_drive_file" small class="ficon" />
					<span class="name" :title="row.unc">{{ row.name }}</span>
					<span class="spacer" />
					<v-icon
						v-tooltip="copiedKey === row.id + ':file' ? 'Copied!' : 'Copy file path'"
						:name="copiedKey === row.id + ':file' ? 'check' : 'content_copy'"
						clickable small class="act" @click="copy(row.unc, row.id + ':file')"
					/>
					<v-icon
						v-tooltip="copiedKey === row.id + ':dir' ? 'Copied!' : 'Copy folder path (paste into Explorer address bar)'"
						:name="copiedKey === row.id + ':dir' ? 'check' : 'folder_copy'"
						clickable small class="act" @click="copy(row.folder, row.id + ':dir')"
					/>
					<a :href="row.fileUri" target="_blank" rel="noopener" class="act">
						<v-icon v-tooltip="'Open (only works with the d1file:// handler or a permissive browser)'" name="open_in_new" clickable small />
					</a>
				</div>
			</div>
			<div class="hint">Tip: Copy the path, then paste it into Windows Explorer’s address bar (or press Win+E first).</div>
		</template>
	</div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useApi } from '@directus/extensions-sdk';

const props = withDefaults(
	defineProps<{
		collection: string;
		primaryKey?: string | number | null;
		relationField?: string;
		uncPrefix?: string;
	}>(),
	{
		primaryKey: null,
		relationField: 'data_files',
		uncPrefix: '\\\\uosfstore.shef.ac.uk\\shared\\star_group1\\',
	},
);

const api = useApi();
const loading = ref(false);
const rows = ref<Array<{ id: string; name: string; unc: string; folder: string; fileUri: string }>>([]);
const copiedKey = ref<string | null>(null);

const hasKey = computed(() => props.primaryKey != null && props.primaryKey !== '+');

function toUnc(archivePath: string): string {
	return props.uncPrefix + archivePath.replace(/\//g, '\\');
}
function parentUnc(unc: string): string {
	return unc.replace(/\\[^\\]*$/, ''); // strip the trailing filename
}
// \\host\share\path  ->  file://host/share/path  (correct UNC file URI)
function toFileUri(unc: string): string {
	const noLead = unc.replace(/^\\\\/, '').replace(/\\/g, '/');
	return 'file://' + encodeURI(noLead);
}

async function load() {
	if (!hasKey.value) {
		rows.value = [];
		return;
	}
	loading.value = true;
	try {
		const rel = props.relationField;
		const res = await api.get(`/items/${props.collection}/${props.primaryKey}`, {
			params: {
				fields: [
					`${rel}.directus_files_id.id`,
					`${rel}.directus_files_id.title`,
					`${rel}.directus_files_id.filename_download`,
					`${rel}.directus_files_id.metadata`,
				],
			},
		});
		const links: any[] = res.data?.data?.[rel] ?? [];
		rows.value = links
			.map((l) => l?.directus_files_id)
			.filter(Boolean)
			.map((f) => {
				const meta = typeof f.metadata === 'string' ? safeParse(f.metadata) : f.metadata || {};
				const ap: string = meta.archive_path || '';
				if (!ap) return null; // uploaded/local file (no archive path) — shown by the native field instead
				const unc = toUnc(ap);
				return {
					id: String(f.id),
					name: f.filename_download || f.title || ap.split('/').pop() || '(file)',
					unc,
					folder: parentUnc(unc),
					fileUri: toFileUri(unc),
				};
			})
			.filter((r): r is NonNullable<typeof r> => r !== null);
	} catch {
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

function safeParse(s: string): any {
	try {
		return JSON.parse(s);
	} catch {
		return {};
	}
}

async function copy(text: string, key: string) {
	try {
		await navigator.clipboard.writeText(text);
	} catch {
		const ta = document.createElement('textarea');
		ta.value = text;
		document.body.appendChild(ta);
		ta.select();
		document.execCommand('copy');
		document.body.removeChild(ta);
	}
	copiedKey.value = key;
	setTimeout(() => (copiedKey.value = null), 1500);
}

onMounted(load);
watch(() => [props.primaryKey, props.collection, props.relationField], load);
</script>

<style scoped>
.d1-archive-links {
	width: 100%;
}
.list {
	border: var(--border-width) solid var(--border-subdued);
	border-radius: var(--border-radius);
}
.row {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 6px 10px;
	border-bottom: var(--border-width) solid var(--border-subdued);
}
.row:last-child {
	border-bottom: none;
}
.name {
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.spacer {
	flex: 1;
}
.act {
	display: inline-flex;
	align-items: center;
	--v-icon-color: var(--foreground-subdued);
	--v-icon-color-hover: var(--primary);
}
.ficon {
	--v-icon-color: var(--foreground-subdued);
}
.hint {
	margin-top: 6px;
	color: var(--foreground-subdued);
	font-size: 12px;
}
</style>
