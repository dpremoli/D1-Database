<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useApi, useStores } from '@directus/extensions-sdk';
import { useRouter } from 'vue-router';

const api = useApi();
const router = useRouter();
const { useUserStore } = useStores();
const userStore = useUserStore();

const firstName = computed(() => (userStore.currentUser as any)?.first_name || 'there');
const greeting = computed(() => {
	const h = new Date().getHours();
	return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
});
const today = computed(() =>
	new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' }),
);

// Bookmark 71 = the "Samples" saved view (filter/layout) on physical_samples,
// set up in Directus itself — link here rather than the bare collection so
// users land on the same curated view as the sidebar bookmark.
const SAMPLES_BOOKMARK = '/content/physical_samples?bookmark=71';

interface Action { label: string; sub: string; icon: string; color: string; to: string; }
const actions: Action[] = [
	{ label: 'Register a sample', sub: 'Add a new physical sample', icon: 'add_circle', color: '#2563eb', to: '/content/physical_samples/+' },
	{ label: 'Log an operation', sub: 'Record a manufacturing step', icon: 'precision_manufacturing', color: '#0d9488', to: '/content/manufacturing_operations/+' },
	{ label: 'Ask the database', sub: 'Chat with your data', icon: 'chat', color: '#7c3aed', to: '/ask-db' },
	{ label: 'Manage people', sub: 'Researchers & operators', icon: 'groups', color: '#db2777', to: '/home/people' },
	{ label: 'Dashboards', sub: 'Explore trends & graphs', icon: 'analytics', color: '#d97706', to: '/d1-lab-dashboard' },
	{ label: 'Force Analysis', sub: 'Machining force & FRM plots', icon: 'insights', color: '#0369a1', to: '/d1-force-dashboard' },
	{ label: 'FAST Analysis', sub: 'Sintering traces & plots', icon: 'whatshot', color: '#ea580c', to: '/d1-fast-dashboard' },
	{ label: 'Force Crawler', sub: '.mat processing queue', icon: 'dns', color: '#65a30d', to: '/d1-force-crawler' },
];

const stats = ref([
	{ label: 'Samples', value: '—', icon: 'science', to: SAMPLES_BOOKMARK },
	{ label: 'Machining', value: '—', icon: 'build', to: '/content/manufacturing_operations' },
	{ label: 'FAST', value: '—', icon: 'whatshot', to: '/d1-fast-dashboard' },
	{ label: 'Tests', value: '—', icon: 'biotech', to: '/content/test_sessions' },
	{ label: 'Campaigns', value: '—', icon: 'flag', to: '/content/campaigns' },
]);

// Recent activity: samples, operations, and tests merged into one feed,
// each tagged with its kind, newest first.
type Kind = 'sample' | 'operation' | 'fast' | 'test';
interface Activity { kind: Kind; id: string; code: string; meta: string; date: string; to: string; }
const KIND_LABEL: Record<Kind, string> = { sample: 'Sample', operation: 'Operation', fast: 'FAST', test: 'Test' };
const KIND_COLOR: Record<Kind, string> = { sample: '#2563eb', operation: '#0d9488', fast: '#ea580c', test: '#7c3aed' };
const recent = ref<Activity[]>([]);

function go(to: string) {
	// The Directus app router base is already /admin — push the bare path.
	router.push(to);
}

function fmtDate(v: string) {
	return v ? new Date(v).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '';
}

async function count(collection: string, filter?: any): Promise<string> {
	try {
		const params: any = { aggregate: { count: '*' }, limit: 1 };
		if (filter) params.filter = filter;
		const res = await api.get(`/items/${collection}`, { params });
		return Number(res.data.data[0].count).toLocaleString('en-GB');
	} catch {
		return '—';
	}
}

onMounted(async () => {
	// Split manufacturing_operations into machining vs FAST (sintering) counts.
	const [s, mach, fast, t, c] = await Promise.all([
		count('physical_samples'),
		count('manufacturing_operations', { process_category: { _neq: 'sintering' } }),
		count('manufacturing_operations', { process_category: { _eq: 'sintering' } }),
		count('test_sessions'), count('campaigns'),
	]);
	stats.value[0].value = s; stats.value[1].value = mach; stats.value[2].value = fast;
	stats.value[3].value = t; stats.value[4].value = c;

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
			to: `/content/physical_samples/${r.sample_id}`,
		}));
		const ops: Activity[] = (opsRes.data.data ?? []).map((r: any) => {
			const isFast = r.process_category === 'sintering';
			return {
				kind: isFast ? 'fast' as const : 'operation' as const,
				id: r.operation_id, code: r.pass_code || r.sample_id?.sample_code || '—',
				meta: r.sample_id?.sample_code || '—', date: r.created_at,
				to: isFast ? `/d1-fast-dashboard?operation=${r.operation_id}` : `/content/manufacturing_operations/${r.operation_id}`,
			};
		});
		const tests: Activity[] = (testsRes.data.data ?? []).map((r: any) => ({
			kind: 'test', id: r.session_id, code: r.test_type || 'Test',
			meta: r.sample_id?.sample_code || '—', date: r.created_at,
			to: `/content/test_sessions/${r.session_id}`,
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
	<private-view title="Home">
		<div class="home">
			<!-- Hero -->
			<section class="hero">
				<div class="hero-text">
					<h1>{{ greeting }}, {{ firstName }}</h1>
					<p>{{ today }} · STARbase Lab</p>
				</div>
			</section>

			<!-- Quick actions -->
			<div class="grid actions">
				<button v-for="a in actions" :key="a.label" class="card action" @click="go(a.to)">
					<span class="chip" :style="{ background: a.color }"><v-icon :name="a.icon" /></span>
					<span class="a-text">
						<span class="a-label">{{ a.label }}</span>
						<span class="a-sub">{{ a.sub }}</span>
					</span>
					<v-icon name="arrow_forward" class="a-go" />
				</button>
			</div>

			<!-- Stats -->
			<div class="grid stats">
				<button v-for="st in stats" :key="st.label" class="card stat" @click="go(st.to)">
					<v-icon :name="st.icon" class="s-icon" />
					<span class="s-value">{{ st.value }}</span>
					<span class="s-label">{{ st.label }}</span>
				</button>
			</div>

			<!-- Recent activity -->
			<section class="recent">
				<div class="section-head">
					<h2>Recent activity</h2>
					<button class="link" @click="go(SAMPLES_BOOKMARK)">View samples →</button>
				</div>
				<div v-if="recent.length" class="grid recent-grid">
					<button v-for="r in recent" :key="`${r.kind}-${r.id}`" class="card rcard" @click="go(r.to)">
						<span class="r-top">
							<span class="r-kind" :style="{ background: KIND_COLOR[r.kind] }">{{ KIND_LABEL[r.kind] }}</span>
							<span class="r-date">{{ fmtDate(r.date) }}</span>
						</span>
						<span class="r-code">{{ r.code }}</span>
						<span class="r-meta">{{ r.meta }}</span>
					</button>
				</div>
				<p v-else class="empty">No activity yet.</p>
			</section>
		</div>
	</private-view>
</template>

<style scoped>
.home {
	max-width: 1080px;
	margin: 0 auto;
	padding: 24px 32px 56px;
	font-family: var(--theme--fonts--sans--font-family, -apple-system, 'Segoe UI', Roboto, sans-serif);
}

/* Hero */
.hero {
	border-radius: 20px;
	padding: 34px 36px;
	margin-bottom: 28px;
	color: #fff;
	background:
		radial-gradient(120% 140% at 100% 0%, rgba(255, 255, 255, 0.18), transparent 55%),
		linear-gradient(120deg, var(--theme--primary, #1d4ed8), #0d9488);
	box-shadow: 0 12px 30px -12px rgba(29, 78, 216, 0.5);
}
.hero h1 { margin: 0; font-size: 30px; font-weight: 750; letter-spacing: -0.01em; }
.hero p { margin: 6px 0 0; font-size: 14px; opacity: 0.9; }

.grid { display: grid; gap: 16px; }
.actions { grid-template-columns: repeat(2, 1fr); margin-bottom: 24px; }
.stats { grid-template-columns: repeat(5, 1fr); margin-bottom: 32px; }
.recent-grid { grid-template-columns: repeat(3, 1fr); }

/* Cards (shared) */
.card {
	border: 1px solid var(--theme--border-color-subdued, #e7ebf0);
	background: var(--theme--background, #fff);
	border-radius: 16px;
	cursor: pointer;
	text-align: left;
	transition: transform 0.14s ease, box-shadow 0.14s ease, border-color 0.14s ease;
	font: inherit;
	color: var(--theme--foreground, #1e293b);
}
.card:hover { transform: translateY(-3px); box-shadow: 0 14px 28px -16px rgba(15, 23, 42, 0.35); border-color: transparent; }

/* Action cards */
.action { display: flex; align-items: center; gap: 16px; padding: 18px 20px; }
.chip {
	width: 46px; height: 46px; border-radius: 13px; flex: 0 0 auto;
	display: grid; place-items: center; color: #fff;
	box-shadow: 0 6px 16px -6px rgba(15, 23, 42, 0.45);
}
.chip :deep(.v-icon) { --v-icon-color: #fff; }
.a-text { display: flex; flex-direction: column; flex: 1; min-width: 0; }
.a-label { font-size: 15.5px; font-weight: 650; }
.a-sub { font-size: 12.5px; color: var(--theme--foreground-subdued, #6b7684); margin-top: 1px; }
.a-go { color: var(--theme--foreground-subdued, #b0b8c3); }

/* Stat cards */
.stat { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; padding: 18px 20px; }
.s-icon { --v-icon-color: var(--theme--primary, #1d4ed8); margin-bottom: 6px; }
.s-value { font-size: 28px; font-weight: 760; letter-spacing: -0.02em; }
.s-label { font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--theme--foreground-subdued, #6b7684); font-weight: 600; }

/* Recent */
.section-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 14px; }
.section-head h2 { margin: 0; font-size: 16px; font-weight: 700; }
.link { border: 0; background: none; cursor: pointer; color: var(--theme--primary, #1d4ed8); font: inherit; font-weight: 600; font-size: 13px; }
.rcard { display: flex; flex-direction: column; gap: 6px; padding: 16px 18px; }
.r-top { display: flex; align-items: center; justify-content: space-between; }
.r-kind {
	font-size: 9.5px; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 700; color: #fff;
	padding: 2px 8px; border-radius: 99px;
}
.r-code { font-family: var(--theme--fonts--monospace--font-family, 'SF Mono', Menlo, monospace); font-weight: 700; font-size: 14px; }
.r-meta { font-size: 12.5px; color: var(--theme--foreground-subdued, #6b7684); }
.r-date { font-size: 11px; color: var(--theme--foreground-subdued, #98a2b3); }
.empty { color: var(--theme--foreground-subdued, #6b7684); }

@media (max-width: 860px) {
	.stats { grid-template-columns: repeat(2, 1fr); }
	.actions, .recent-grid { grid-template-columns: 1fr; }
}
</style>
