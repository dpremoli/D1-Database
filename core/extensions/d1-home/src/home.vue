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

interface Action { label: string; sub: string; icon: string; color: string; to: string; }
const actions: Action[] = [
	{ label: 'Register a sample', sub: 'Add a new physical sample', icon: 'add_circle', color: '#2563eb', to: '/content/physical_samples/+' },
	{ label: 'Log an operation', sub: 'Record a manufacturing step', icon: 'precision_manufacturing', color: '#0d9488', to: '/content/manufacturing_operations/+' },
	{ label: 'Ask the database', sub: 'Chat with your data', icon: 'chat', color: '#7c3aed', to: '/ask-db' },
	{ label: 'Manage people', sub: 'Researchers & operators', icon: 'groups', color: '#db2777', to: '/home/people' },
	{ label: 'Dashboards', sub: 'Explore trends & graphs', icon: 'analytics', color: '#d97706', to: '/d1-lab-dashboard' },
];

const stats = ref([
	{ label: 'Samples', value: '—', icon: 'science', to: '/content/physical_samples' },
	{ label: 'Operations', value: '—', icon: 'build', to: '/content/manufacturing_operations' },
	{ label: 'Tests', value: '—', icon: 'biotech', to: '/content/test_sessions' },
	{ label: 'Campaigns', value: '—', icon: 'flag', to: '/content/campaigns' },
]);
const recent = ref<any[]>([]);

function go(to: string) {
	// The Directus app router base is already /admin — push the bare path.
	router.push(to);
}

function fmtDate(v: string) {
	return v ? new Date(v).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '';
}

async function count(collection: string): Promise<string> {
	try {
		const res = await api.get(`/items/${collection}`, { params: { aggregate: { count: '*' }, limit: 1 } });
		return Number(res.data.data[0].count).toLocaleString('en-GB');
	} catch {
		return '—';
	}
}

onMounted(async () => {
	const [s, o, t, c] = await Promise.all([
		count('physical_samples'), count('manufacturing_operations'), count('test_sessions'), count('campaigns'),
	]);
	stats.value[0].value = s; stats.value[1].value = o; stats.value[2].value = t; stats.value[3].value = c;

	try {
		const res = await api.get('/items/physical_samples', {
			params: { sort: '-created_at', limit: 6, fields: ['sample_id', 'sample_code', 'form', 'current_status', 'created_at', 'material_id.common_name'] },
		});
		recent.value = res.data.data;
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

			<!-- Recent samples -->
			<section class="recent">
				<div class="section-head">
					<h2>Recent samples</h2>
					<button class="link" @click="go('/content/physical_samples')">View all →</button>
				</div>
				<div v-if="recent.length" class="grid recent-grid">
					<button
						v-for="r in recent"
						:key="r.sample_id"
						class="card rcard"
						@click="go(`/content/physical_samples/${r.sample_id}`)"
					>
						<span class="r-code">{{ r.sample_code }}</span>
						<span class="r-meta">{{ r.material_id?.common_name || '—' }}<template v-if="r.form"> · {{ r.form }}</template></span>
						<span class="r-foot">
							<span v-if="r.current_status" class="r-status">{{ r.current_status }}</span>
							<span class="r-date">{{ fmtDate(r.created_at) }}</span>
						</span>
					</button>
				</div>
				<p v-else class="empty">No samples yet.</p>
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
.stats { grid-template-columns: repeat(4, 1fr); margin-bottom: 32px; }
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
.r-code { font-family: var(--theme--fonts--monospace--font-family, 'SF Mono', Menlo, monospace); font-weight: 700; font-size: 14px; }
.r-meta { font-size: 12.5px; color: var(--theme--foreground-subdued, #6b7684); }
.r-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 4px; }
.r-status {
	font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 700;
	color: var(--theme--primary, #1d4ed8); background: color-mix(in srgb, var(--theme--primary, #1d4ed8) 12%, transparent);
	padding: 2px 8px; border-radius: 99px;
}
.r-date { font-size: 11px; color: var(--theme--foreground-subdued, #98a2b3); }
.empty { color: var(--theme--foreground-subdued, #6b7684); }

@media (max-width: 860px) {
	.stats { grid-template-columns: repeat(2, 1fr); }
	.actions, .recent-grid { grid-template-columns: 1fr; }
}
</style>
