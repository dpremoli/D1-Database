// Shared state for the modular Recording workspace. Created once in RecordPage and provided to
// every panel via inject(), so panels stay small and independent while sharing one RecordClient,
// config, metadata, plot options, and the start/stop/replay actions.
import { computed, inject, reactive, ref, shallowRef, watch, type InjectionKey } from 'vue';
import { RecordClient } from './liveClient';
import { api } from '../directusClient';
import { parseCache, type Cache } from '../force/liveCache';
import { searchSamples, searchOperators, searchEquipment, getMethods, resolveMachiningMethodId, type LookupItem } from './directusLookups';
import { logRun, syncStatus } from './directusSync';
import { alarmController } from './alarms';
import { labamp, type AutoRangeRec } from './labampApi';

export type Axis = 'Fx' | 'Fy' | 'Fz';

export interface ReplayOption { label: string; cacheId: string; opId: string; }

export function createWorkspace() {
	const client = new RecordClient();
	const source = ref<'sim' | 'replay' | 'nidaq'>('sim');
	// NI-DAQ physical channels (2b), one per SIGNAL_CHANNEL, edited as newline text. Placeholders —
	// the operator sets the real device/channel strings on the rig.
	const nidaqChannels = ref(
		['cDAQ1Mod1/ai0', 'cDAQ1Mod1/ai1', 'cDAQ1Mod1/ai2', 'cDAQ1Mod1/ai3',
			'cDAQ1Mod2/ai0', 'cDAQ1Mod2/ai1', 'cDAQ1Mod2/ai2', 'cDAQ1Mod2/ai3', 'cDAQ1Mod3/ai0'].join('\n'),
	);

	const cfg = reactive({
		rpm: 1200, feed: 0.05, diam: 80, inner_diam: 0,
		sample_rate: 25000, duration_sec: 8, ppr: 1,
		drift_comp: false,   // optional drift compensation on the saved .mat/live_cache (raw stays raw)
		frm_from_cut: true,  // live FRM begins at the detected cut start
	});
	const meta = reactive<Record<string, string>>({
		sample_name: 'SIM-CUT-001', sample_code: '', operation: '', op_type: '',
		insert: '', edge_id: '', tool: '', machine: '', coolant: '', notes: '',
	});
	// Extra machining fields mirroring the Directus manufacturing_operations form (folded section).
	const machining = reactive<{ axial_doc: string; radial_doc: string; cutting_length: string; coolant_pressure: string; operation_sequence: string; chips_ref: string; new_edge: boolean; chips_collected: boolean }>(
		{ axial_doc: '', radial_doc: '', cutting_length: '', coolant_pressure: '', operation_sequence: '', chips_ref: '', new_edge: false, chips_collected: false },
	);
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

	// Directus links for the run write-back (2d)
	const link = reactive({ sampleId: '', sampleLabel: '', operatorId: '', operatorLabel: '', equipmentId: '', equipmentLabel: '' });
	const logged = ref(false);

	// Safety alarms (2e) — the app-wide controller (config lives in Settings > Alarms), evaluated
	// here on every live frame while recording.
	const alarms = alarmController;
	watch(() => client.frameSeq.value, () => { if (st.state === 'recording') alarms.evaluate(st.peaks, st.rpm, cfg.rpm); });

	// Converging between-cuts auto-range: after each cut, recommend + apply the next-pass per-channel
	// ranges from THIS cut's recorded per-channel peaks (summary.channels_ranging). Applying them to
	// the amp is enough — the next nidaq run re-derives its N/V gains from the amp's ranges. Range
	// changes only ever happen here, between cuts, never mid-cut (which the charge amp can't do
	// cleanly). Clipped channels over-shoot upward and converge back down over the next pass or two.
	const converge = reactive<{ enabled: boolean; busy: boolean; status: string | null; recs: AutoRangeRec[] | null }>(
		{ enabled: false, busy: false, status: null, recs: null },
	);
	async function convergeAfterCut() {
		const cr = st.summary?.channels_ranging;
		if (!cr || !Array.isArray(cr.peaks_n)) { converge.status = 'no per-channel peaks in this capture'; return; }
		converge.busy = true;
		try {
			const res = await labamp.converge({ peaks: cr.peaks_n, clipped: cr.clipped, currents: cr.ranges_n, apply: true });
			converge.recs = res.recommendations;
			const clipped = res.recommendations.filter((r) => r.clipped).map((r) => r.channel);
			const over = Object.entries(res.status || {}).filter(([, s]) => s !== 'OK').map(([c]) => c);
			converge.status = clipped.length
				? `ranged up ch ${clipped.join(', ')} (railed) — set for next pass`
				: over.length ? `applied; ch ${over.join(', ')} still over-range` : 'ranges converged for next pass';
		} catch (e: any) {
			converge.status = `converge failed: ${e?.message || e}`;
		} finally { converge.busy = false; }
	}
	// Fire once per completed cut (covers both manual stop and self-terminating duration runs).
	watch(() => st.state, (s, prev) => { if (s === 'done' && prev !== 'done' && converge.enabled) convergeAfterCut(); });

	function onSelectSample(it: LookupItem) {
		link.sampleLabel = it.label;
		meta.sample_name = it.label;
		meta.sample_code = it.label;
		const d = Number(it.extra?.diameter_mm);
		if (Number.isFinite(d) && d > 0) cfg.diam = d;  // auto-fill Ø from the sample
	}

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
		alarms.reset();
		try {
			if (source.value === 'replay') {
				if (!replay.cacheId) throw new Error('pick a cut to replay');
				const res = await api.get(`/assets/${replay.cacheId}`, { responseType: 'arraybuffer' });
				await client.startReplay(res.data as ArrayBuffer, {
					sample_name: meta.sample_name || replay.label || 'REPLAY',
					axis: plot.frmAxis, ppr: cfg.ppr, speed: replay.speed, extra_metadata: metaObj(),
				});
			} else if (source.value === 'nidaq') {
				const chans = nidaqChannels.value.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean);
				await client.start({ ...cfg, source: 'nidaq', nidaq_channels: chans, axis: plot.frmAxis, extra_metadata: metaObj() } as any);
			} else {
				await client.start({ ...cfg, source: 'sim', axis: plot.frmAxis, extra_metadata: metaObj() } as any);
			}
		} catch (e: any) {
			const m = e?.message || 'failed to start';
			// A bare "Failed to fetch"/"Load failed" is a transport failure reaching the recorder
			// (backend down, or blocked by CORS / HTTPS mixed-content) — spell that out.
			errMsg.value = /failed to fetch|load failed|networkerror/i.test(m)
				? `${m} — can't reach the recording backend. Is it running on this machine?`
				: m;
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

	function newRun() { client.reset(); finishedCache.value = null; errMsg.value = null; logged.value = false; }

	// Build + enqueue the manufacturing_operations run record (offline-queued in directusSync).
	function buildRunPayload(): Record<string, any> {
		const surface = Math.PI * cfg.diam * cfg.rpm / 1000;
		const num = (s: string) => (s !== '' && Number.isFinite(Number(s)) ? Number(s) : null);
		return {
			sample_id: link.sampleId || null,
			operator_person_id: link.operatorId || null,
			equipment_id: link.equipmentId || null,
			operation_date: new Date().toISOString(),
			pass_code: (meta.operation && meta.operation.trim()) || `${meta.sample_code || meta.sample_name || 'REC'}-${Date.now()}`,
			process_category: 'machining',
			machining_operation_subtype: meta.op_type || null,
			machining_spindle_speed_rpm: cfg.rpm,
			machining_feed_mm_per_rev: cfg.feed,
			machining_workpiece_diameter_mm: cfg.diam,
			machining_cutting_speed_m_per_min: Number(surface.toFixed(2)),
			machining_force_captured: true,
			machining_tacho_used: true,
			machining_coolant_used: !!(meta.coolant && meta.coolant.trim()),
			capture_software: 'force-app',
			capture_frequency_khz: Number((cfg.sample_rate / 1000).toFixed(3)),
			outcome_notes: meta.notes || null,
			// Machining details (folded Directus form section)
			machining_axial_depth_of_cut_mm: num(machining.axial_doc),
			machining_radial_depth_of_cut_mm: num(machining.radial_doc),
			machining_cutting_length_mm: num(machining.cutting_length),
			machining_coolant_pressure_bar: num(machining.coolant_pressure),
			operation_sequence: num(machining.operation_sequence),
			machining_new_edge: machining.new_edge,
			machining_chips_collected: machining.chips_collected,
			machining_chips_ref_code: machining.chips_ref || null,
			recorded_metadata: {
				...metaObj(), capture_id: st.captureId, peaks: st.summary?.peaks,
				source: source.value, replay_of: source.value === 'replay' ? replay.label : undefined,
			},
		};
	}
	async function logRunNow(): Promise<void> {
		const payload = buildRunPayload();
		// method_id is required on manufacturing_operations; resolve from the cached method list
		// (warmed at load, so this works even offline).
		payload.method_id = await resolveMachiningMethodId(meta.op_type).catch(() => null);
		await logRun(payload);
		logged.value = true;
	}

	// Warm the methods cache so the required method_id resolves even if we're offline at log time.
	getMethods().catch(() => {});

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
		client, source, nidaqChannels, cfg, meta, machining, plot, replay, st, busy, errMsg, finishedCache,
		isIdle, isRecording, isFinalizing, isDone, locked,
		start, stop, newRun, loadFinished, searchCuts, metaObj,
		// 2d: Directus links + run write-back
		link, logged, onSelectSample, logRunNow, syncStatus,
		searchSamples, searchOperators, searchEquipment,
		// 2e: safety alarms
		alarms,
		// converging between-cuts auto-range
		converge, convergeAfterCut,
	};
}

export type Workspace = ReturnType<typeof createWorkspace>;
export const WORKSPACE: InjectionKey<Workspace> = Symbol('record-workspace');
export function useWorkspace(): Workspace {
	const w = inject(WORKSPACE);
	if (!w) throw new Error('useWorkspace() outside a workspace provider');
	return w;
}
