<template>
	<div class="d1-machining">
		<!-- Panel 1: Equipment -->
		<div class="d1-panel">
			<div class="d1-panel-header">
				<v-icon name="precision_manufacturing" />
				<h3>Equipment</h3>
				<v-input v-model="equipmentSearch" placeholder="Search…" small class="d1-search" />
			</div>
			<div class="d1-list">
				<div
					v-for="eq in filteredEquipment"
					:key="eq.equipment_id"
					class="d1-row"
					:class="{ active: selectedEquipmentId === eq.equipment_id }"
					@click="selectEquipment(eq)"
				>
					<span class="d1-primary">{{ eq.equipment_name }}</span>
					<span class="d1-secondary">{{ eq.equipment_type }}</span>
				</div>
				<div v-if="filteredEquipment.length === 0" class="d1-empty">No equipment found</div>
			</div>
		</div>

		<!-- Panel 2: Operations -->
		<div class="d1-panel">
			<div class="d1-panel-header">
				<v-icon name="build" />
				<h3>Operations</h3>
				<span v-if="selectedEquipmentId" class="d1-count">{{ operations.length }}</span>
			</div>
			<div v-if="!selectedEquipmentId" class="d1-empty">Select equipment to filter operations</div>
			<div v-else-if="loadingOps" class="d1-loading"><v-progress-circular indeterminate /></div>
			<div v-else class="d1-list">
				<div
					v-for="op in operations"
					:key="op.operation_id"
					class="d1-row"
					:class="{ active: selectedOp?.operation_id === op.operation_id }"
					@click="selectOp(op)"
				>
					<span class="d1-primary">
						{{ op.sample_id?.sample_code ?? '—' }}
						<span class="d1-badge">{{ op.method_id?.method_name ?? op.operation_type }}</span>
					</span>
					<span class="d1-secondary">
						{{ op.insert_edge_id?.edge_code ?? '—' }} · {{ op.tool_id?.tool_code ?? '—' }}
					</span>
					<span class="d1-date">{{ formatDate(op.operation_date) }}</span>
				</div>
				<div v-if="operations.length === 0" class="d1-empty">No operations for this machine</div>
			</div>
		</div>

		<!-- Panel 3: Detail + Sample -->
		<div class="d1-panel">
			<div class="d1-panel-header">
				<v-icon name="info" />
				<h3>Operation Detail</h3>
			</div>
			<div v-if="!selectedOp" class="d1-empty">Select an operation</div>
			<div v-else class="d1-detail">
				<div class="d1-detail-section">
					<h4>Sample</h4>
					<div class="d1-kv">
						<span>Code</span><span>{{ selectedOp.sample_id?.sample_code ?? '—' }}</span>
						<span>Nickname</span><span>{{ selectedOp.sample_id?.nickname ?? '—' }}</span>
						<span>Material</span><span>{{ selectedOp.sample_id?.material_id?.common_name ?? '—' }}</span>
					</div>
				</div>
				<div class="d1-detail-section">
					<h4>Tooling</h4>
					<div class="d1-kv">
						<span>Insert Edge</span><span>{{ selectedOp.insert_edge_id?.edge_code ?? '—' }}</span>
						<span>Tool</span><span>{{ selectedOp.tool_id?.tool_code ?? '—' }}</span>
						<span>Method</span><span>{{ selectedOp.method_id?.method_name ?? '—' }}</span>
					</div>
				</div>
				<div class="d1-detail-section">
					<h4>Parameters</h4>
					<div class="d1-kv">
						<span>Op Type</span><span>{{ selectedOp.operation_type ?? '—' }}</span>
						<span>Date</span><span>{{ formatDate(selectedOp.operation_date) }}</span>
						<span>Outcome</span><span>{{ selectedOp.outcome ?? '—' }}</span>
					</div>
				</div>
				<div v-if="selectedOp.parameters && Object.keys(selectedOp.parameters).length" class="d1-detail-section">
					<h4>Metadata</h4>
					<div class="d1-kv">
						<template v-for="(v, k) in selectedOp.parameters" :key="k">
							<span>{{ k }}</span><span>{{ v }}</span>
						</template>
					</div>
				</div>
				<div class="d1-detail-section">
					<h4>Notes</h4>
					<p class="d1-notes">{{ selectedOp.notes || '—' }}</p>
				</div>
			</div>
		</div>

		<!-- Panel 4: Node Graph -->
		<div class="d1-panel d1-panel--graph">
			<div class="d1-panel-header">
				<v-icon name="hub" />
				<h3>Connections</h3>
			</div>
			<NodeGraph ref="graphRef" class="d1-graph" />
		</div>
	</div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue';
import { useD1Items } from '../composables/useD1Items';
import NodeGraph from './NodeGraph.vue';

const { getItems } = useD1Items();

const equipment = ref<any[]>([]);
const equipmentSearch = ref('');
const selectedEquipmentId = ref<string | null>(null);
const selectedEquipmentCollection = 'equipment';

const operations = ref<any[]>([]);
const loadingOps = ref(false);
const selectedOp = ref<any | null>(null);

const graphRef = ref<InstanceType<typeof NodeGraph> | null>(null);

const filteredEquipment = computed(() =>
	equipmentSearch.value
		? equipment.value.filter((e) =>
			e.equipment_name?.toLowerCase().includes(equipmentSearch.value.toLowerCase())
		)
		: equipment.value
);

onMounted(async () => {
	equipment.value = await getItems('equipment', {
		'fields[]': ['equipment_id', 'equipment_name', 'equipment_type'],
		'sort[]': 'equipment_name',
		limit: 200,
	});
});

async function selectEquipment(eq: any) {
	selectedEquipmentId.value = eq.equipment_id;
	selectedOp.value = null;
	loadingOps.value = true;
	try {
		operations.value = await getItems('manufacturing_operations', {
			'filter[equipment_id][_eq]': eq.equipment_id,
			'fields[]': [
				'*',
				'sample_id.sample_code',
				'sample_id.nickname',
				'sample_id.material_id.common_name',
				'insert_edge_id.edge_code',
				'tool_id.tool_code',
				'method_id.method_name',
			],
			'sort[]': '-operation_date',
			limit: 500,
		});
	} finally {
		loadingOps.value = false;
	}
	graphRef.value?.loadNeighbors(selectedEquipmentCollection, eq.equipment_id);
}

function selectOp(op: any) {
	selectedOp.value = op;
	graphRef.value?.loadNeighbors('manufacturing_operations', op.operation_id);
}

function formatDate(d: string | null): string {
	if (!d) return '—';
	return new Date(d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}
</script>

<style scoped>
.d1-machining {
	display: grid;
	grid-template-columns: 220px 1fr 280px 320px;
	gap: 12px;
	height: calc(100vh - 120px);
	padding: 12px;
	overflow: hidden;
}

.d1-panel {
	display: flex;
	flex-direction: column;
	background: var(--background-page);
	border: 1px solid var(--border-normal);
	border-radius: var(--border-radius);
	overflow: hidden;
}

.d1-panel--graph {
	overflow: hidden;
}

.d1-panel-header {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 10px 12px;
	border-bottom: 1px solid var(--border-normal);
	background: var(--background-normal);
	flex-shrink: 0;
}

.d1-panel-header h3 {
	margin: 0;
	font-size: 13px;
	font-weight: 600;
	flex: 1;
}

.d1-search {
	width: 100%;
	margin-top: 4px;
}

.d1-count {
	font-size: 11px;
	background: var(--primary-alt);
	color: var(--primary);
	padding: 2px 6px;
	border-radius: 10px;
	font-weight: 600;
}

.d1-list {
	overflow-y: auto;
	flex: 1;
}

.d1-row {
	padding: 8px 12px;
	cursor: pointer;
	border-bottom: 1px solid var(--border-subdued);
	display: flex;
	flex-direction: column;
	gap: 2px;
	transition: background-color var(--fast) var(--transition);
}

.d1-row:hover {
	background: var(--background-normal-alt);
}

.d1-row.active {
	background: var(--primary-alt);
	border-left: 3px solid var(--primary);
}

.d1-primary {
	font-size: 13px;
	font-weight: 500;
	display: flex;
	align-items: center;
	gap: 6px;
}

.d1-secondary {
	font-size: 11px;
	color: var(--foreground-subdued);
}

.d1-date {
	font-size: 10px;
	color: var(--foreground-subdued);
}

.d1-badge {
	font-size: 10px;
	background: var(--background-normal-alt);
	padding: 1px 5px;
	border-radius: 4px;
	font-weight: 400;
}

.d1-empty {
	padding: 24px;
	text-align: center;
	color: var(--foreground-subdued);
	font-size: 13px;
}

.d1-loading {
	display: flex;
	justify-content: center;
	padding: 24px;
}

.d1-detail {
	overflow-y: auto;
	flex: 1;
	padding: 12px;
	display: flex;
	flex-direction: column;
	gap: 12px;
}

.d1-detail-section h4 {
	font-size: 11px;
	font-weight: 700;
	text-transform: uppercase;
	letter-spacing: 0.5px;
	color: var(--foreground-subdued);
	margin: 0 0 6px;
}

.d1-kv {
	display: grid;
	grid-template-columns: 100px 1fr;
	gap: 4px 8px;
	font-size: 13px;
}

.d1-kv span:nth-child(odd) {
	color: var(--foreground-subdued);
}

.d1-kv span:nth-child(even) {
	font-weight: 500;
}

.d1-notes {
	font-size: 13px;
	color: var(--foreground-normal);
	margin: 0;
	white-space: pre-wrap;
}

.d1-graph {
	flex: 1;
	min-height: 0;
}
</style>
