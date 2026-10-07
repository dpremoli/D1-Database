<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useApi } from '@directus/extensions-sdk';
import { formatDate, recordRoute } from '@d1/ui';
import { samplesBookmarkLink, SAMPLES_LIST } from './samplesBookmark';

// Recent activity: samples, operations and tests merged into one feed, each tagged with its kind,
// newest first. Links go through recordRoute (FAST runs open the FAST dashboard, as before).
type Kind = 'sample' | 'operation' | 'fast' | 'test';
interface Activity { kind: Kind; id: string; code: string; meta: string; date: string; to: string }
const KIND_LABEL: Record<Kind, string> = { sample: 'Sample', operation: 'Operation', fast: 'FAST', test: 'Test' };

const api = useApi();
const recent = ref<Activity[]>([]);
const samplesLink = ref(SAMPLES_LIST);

onMounted(async () => {
	samplesBookmarkLink(api).then((to) => (samplesLink.value = to));
	try {
		const [samplesRes, opsRes, testsRes] = await Promise.all([
			api.get('/items/physical_samples', {
				params: { sort: '-created_at', limit: 6, fields: ['sample_id', 'sample_code', 'form', 'created_at', 'material_id.common_name'] },
			}),
			api.get('/items/manufacturing_operations', {
				params: { sort: '-created_at', limit: 8, fields: ['operation_id', 'pass_code', 'created_at', 'process_category', 'sample_id.sample_code'] },
			}),
			api.get('/items/test_sessions', {
				params: { sort: '-created_at', limit: 6, fields: ['session_id', 'test_type', 'created_at', 'sample_id.sample_code'] },
			}),
		]);
		const samples: Activity[] = (samplesRes.data.data ?? []).map((r: any) => ({
			kind: 'sample', id: r.sample_id, code: r.sample_code,
			meta: r.material_id?.common_name || r.form || '—', date: r.created_at,
			to: recordRoute('physical_samples', r.sample_id),
		}));
		const ops: Activity[] = (opsRes.data.data ?? []).map((r: any) => {
			const isFast = r.process_category === 'sintering';
			return {
				kind: isFast ? ('fast' as const) : ('operation' as const),
				id: r.operation_id, code: r.pass_code || r.sample_id?.sample_code || '—',
				meta: r.sample_id?.sample_code || '—', date: r.created_at,
				to: isFast ? `/d1-fast-dashboard?operation=${r.operation_id}` : recordRoute('manufacturing_operations', r.operation_id),
			};
		});
		const tests: Activity[] = (testsRes.data.data ?? []).map((r: any) => ({
			kind: 'test', id: r.session_id, code: r.test_type || 'Test',
			meta: r.sample_id?.sample_code || '—', date: r.created_at,
			to: recordRoute('test_sessions', r.session_id),
		}));
		recent.value = [...samples, ...ops, ...tests]
			.filter((a) => a.date)
			.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime())
			.slice(0, 9);
	} catch {
		recent.value = [];
	}
});
</script>

<template>
	<section aria-labelledby="recent-h">
		<div class="section-head">
			<h2 id="recent-h">Recent activity</h2>
			<router-link :to="samplesLink" class="link">View samples →</router-link>
		</div>
		<div v-if="recent.length" class="recent-grid">
			<router-link v-for="r in recent" :key="`${r.kind}-${r.id}`" :to="r.to" class="rcard">
				<span class="r-top">
					<span class="r-kind" :class="`k-${r.kind}`">{{ KIND_LABEL[r.kind] }}</span>
					<span class="r-date">{{ formatDate(r.date) }}</span>
				</span>
				<span class="r-code">{{ r.code }}</span>
				<span class="r-meta">{{ r.meta }}</span>
			</router-link>
		</div>
		<p v-else class="empty">No activity yet.</p>
	</section>
</template>

<style scoped>
.section-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 14px; }
.section-head h2 { margin: 0; font-size: 18px; font-weight: 750; }
.link { color: var(--theme--primary); font-weight: 600; font-size: 13px; text-decoration: none; }
.link:hover { text-decoration: underline; }
.recent-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; }
.rcard {
	display: flex; flex-direction: column; gap: 6px; padding: 14px 16px; min-width: 0; text-decoration: none;
	border: 1px solid var(--theme--border-color-subdued); border-radius: 14px;
	background: var(--theme--background); color: var(--theme--foreground);
	transition: border-color 0.14s ease, box-shadow 0.14s ease;
}
.rcard:hover { border-color: var(--theme--primary); box-shadow: 0 10px 22px -16px rgba(15, 23, 42, 0.4); }
.r-top { display: flex; align-items: center; justify-content: space-between; }
.r-kind { font-size: 9.5px; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 700; padding: 2px 8px; border-radius: 99px; }
.k-sample { color: var(--theme--primary); background: var(--theme--primary-background); }
.k-operation { color: var(--theme--success); background: var(--theme--success-background); }
.k-fast { color: var(--theme--warning); background: var(--theme--warning-background); }
.k-test { color: var(--theme--foreground-subdued); background: var(--theme--background-normal); }
.r-code { font-family: var(--theme--fonts--monospace--font-family, monospace); font-weight: 700; font-size: 14px; overflow-wrap: anywhere; }
.r-meta { font-size: 12.5px; color: var(--theme--foreground-subdued); }
.r-date { font-size: 11px; color: var(--theme--foreground-subdued); }
.empty { color: var(--theme--foreground-subdued); }
</style>
