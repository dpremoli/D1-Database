// Shared state for the modular Recording workspace. Created once in RecordPage and provided to
// every panel via inject(), so panels stay small and independent while sharing one RecordClient,
// config, metadata, plot options, and the start/stop/replay actions.
import { computed, inject, reactive, ref, shallowRef, type InjectionKey } from 'vue';
import { RecordClient } from './liveClient';
import { api } from '../directusClient';
import { parseCache, type Cache } from '../force/liveCache';

export type Axis = 'Fx' | 'Fy' | 'Fz';

export interface ReplayOption { label: string; cacheId: string; opId: string; }

export function createWorkspace() {
	const client = new RecordClient();
	const source = ref<'sim' | 'replay'>('sim');

	const cfg = reactive({
		rpm: 1200, feed: 0.05, diam: 80, inner_diam: 0,
		sample_rate: 25000, duration_sec: 8, ppr: 1,
	});
	const meta = reactive<Record<string, string>>({
		sample_name: 'SIM-CUT-001', sample_code: '', operation: '', op_type: '',
		insert: '', edge_id: '', tool: '', machine: '', coolant: '', notes: '',
	});
	const plot = reactive<{ forceMode: 'time' | 'fft'; frmAxis: Axis; colormap: string; pointSize: number }>({
		forceMode: 'time', frmAxis: 'Fz', colormap: 'viridis', pointSize: 1.8,
	});
	const replay = reactive<{ query: string; options: ReplayOption[]; cacheId: string; label: string; speed: number; loading: boolean }>(
		{ query: '', options: [], cacheId: '', label: '', speed: 20, loading: false },
	);

	const busy = ref(false);
	const errMsg = ref<string | null>(null);
	const finishedCache = shallowRef<Cache | null>(null);
	const st = client.status;

	const isIdle = computed(() => st.state === 'idle');
	const isRecording = computed(() => st.state === 'recording');
	const isFinalizing = computed(() => st.state === 'finalizing');
	const isDone = computed(() => st.state === 'done');
	const locked = computed(() => isRecording.value || isFinalizing.value);

	function metaObj(): Record<string, string> {
		const o: Record<string, string> = {};
		for (const [k, v] of Object.entries(meta)) if (v && v.trim()) o[k] = v.trim();
		return o;
	}

	async function start() {
		if (busy.value) return;
		busy.value = true; errMsg.value = null; finishedCache.value = null;
		try {
			if (source.value === 'replay') {
				if (!replay.cacheId) throw new Error('pick a cut to replay');
				const res = await api.get(`/assets/${replay.cacheId}`, { responseType: 'arraybuffer' });
				await client.startReplay(res.data as ArrayBuffer, {
					sample_name: meta.sample_name || replay.label || 'REPLAY',
					axis: plot.frmAxis, ppr: cfg.ppr, speed: replay.speed, extra_metadata: metaObj(),
				});
			} else {
				await client.start({ ...cfg, axis: plot.frmAxis, extra_metadata: metaObj() } as any);
			}
		} catch (e: any) {
			errMsg.value = e?.message || 'failed to start';
		} finally {
			busy.value = false;
		}
	}

	async function stop() {
		if (busy.value) return;
		busy.value = true;
		try { await client.stop(); await loadFinished(); } finally { busy.value = false; }
	}

	async function loadFinished() {
		const id = st.captureId;
		if (!id) return;
		try {
			const res = await fetch(client.cacheUrl(id));
			if (res.ok) finishedCache.value = parseCache(await res.arrayBuffer());
		} catch { /* best-effort */ }
	}

	function newRun() { client.reset(); finishedCache.value = null; errMsg.value = null; }

	// Directus-backed cut picker for replay: search done analyses by operation pass code.
	async function searchCuts(q: string) {
		replay.loading = true;
		try {
			const filter: any = { status: { _eq: 'done' }, live_cache_file: { _nnull: true } };
			if (q && q.trim()) filter['operation_id'] = { pass_code: { _icontains: q.trim() } };
			const res = await api.get('/items/machining_force_analysis', {
				params: { filter, limit: 25, fields: ['id', 'live_cache_file', 'operation_id.pass_code'], sort: 'operation_id.pass_code' },
			});
			replay.options = (res.data?.data ?? []).map((r: any) => ({
				label: r.operation_id?.pass_code || r.id, cacheId: r.live_cache_file, opId: r.id,
			})).filter((o: ReplayOption) => o.cacheId);
		} catch { replay.options = []; } finally { replay.loading = false; }
	}

	return {
		client, source, cfg, meta, plot, replay, st, busy, errMsg, finishedCache,
		isIdle, isRecording, isFinalizing, isDone, locked,
		start, stop, newRun, loadFinished, searchCuts, metaObj,
	};
}

export type Workspace = ReturnType<typeof createWorkspace>;
export const WORKSPACE: InjectionKey<Workspace> = Symbol('record-workspace');
export function useWorkspace(): Workspace {
	const w = inject(WORKSPACE);
	if (!w) throw new Error('useWorkspace() outside a workspace provider');
	return w;
}
