// Shared state for the modular Recording workspace. Created once in RecordPage and provided to
// every panel via inject(), so panels stay small and independent while sharing one RecordClient,
// config, metadata, plot options, and the start/stop/replay actions.
import { computed, inject, reactive, ref, shallowRef, watch, type InjectionKey } from 'vue';
import { RAW_BYTES_PER_SAMPLE, RAW_COLUMNS, RecordClient } from './liveClient';
import { api } from '../directusClient';
import { buildSeriesEnvelope, parseCache, type Cache } from '../force/liveCache';
import { searchSamples, searchOperators, searchEquipment, searchTools, searchInserts, searchEdges, getMethods, resolveMachiningMethodId, type LookupItem } from './directusLookups';
import { logRun, syncStatus } from './directusSync';
import { alarmController } from './alarms';
import { labamp, type AutoRangeRec } from './labampApi';

export type Axis = 'Fx' | 'Fy' | 'Fz';

export interface ReplayOption { label: string; cacheId: string; opId: string; operationId: string | null; }

// The "Operation type" select's values are short codes (MT-* = machining/turning, MM-* =
// machining/milling, 'other' = no category) — this is the single place that maps a code to the
// broad category used to filter Machine/Tool lookups and the replay cut list. Only turning/milling
// are distinguished since that's what the underlying equipment_type/tool_type free-text fields
// actually distinguish in practice (see directusLookups.ts).
export function opTypeCategory(opType: string): 'turning' | 'milling' | null {
	if (opType.startsWith('MT')) return 'turning';
	if (opType.startsWith('MM')) return 'milling';
	return null;
}

export function createWorkspace() {
	const client = new RecordClient();
	const SOURCE_LS_KEY = 'force-app.source';
	const storedSource = localStorage.getItem(SOURCE_LS_KEY);
	const source = ref<'sim' | 'replay' | 'nidaq'>(storedSource === 'sim' || storedSource === 'replay' || storedSource === 'nidaq' ? storedSource : 'sim');
	// Persist the user's explicit choice so the NI-DAQ auto-detect below (which re-runs on every
	// page mount, not just once ever) only ever applies a default the first time this browser has
	// been used — it must never silently override a choice the user already made. Without this, a
	// machine with real/simulated NI-DAQ hardware present forces source back to 'nidaq' on every
	// reload even after explicitly picking "Simulated". A plain `watch(source, ...)` isn't enough
	// on its own: source already defaults to 'sim', so clicking "Simulated" (same value) fires no
	// change event, and the auto-detect's fetch can still resolve afterward and overwrite it — so
	// setSource() below writes to localStorage unconditionally and synchronously, and the
	// auto-detect re-reads localStorage fresh (not a value captured before the click) right before
	// it would apply, closing the race regardless of which finishes first.
	function setSource(s: 'sim' | 'replay' | 'nidaq') { source.value = s; localStorage.setItem(SOURCE_LS_KEY, s); }
	const NIDAQ_LS_KEY = 'force-app.nidaq.channels';
	const defaultChannels = ['cDAQ1Mod1/ai0', 'cDAQ1Mod1/ai1', 'cDAQ1Mod1/ai2', 'cDAQ1Mod1/ai3',
		'cDAQ1Mod2/ai0', 'cDAQ1Mod2/ai1', 'cDAQ1Mod2/ai2', 'cDAQ1Mod2/ai3', 'cDAQ1Mod3/ai0'].join('\n');
	const nidaqChannels = ref(localStorage.getItem(NIDAQ_LS_KEY) || defaultChannels);
	watch(nidaqChannels, (v) => localStorage.setItem(NIDAQ_LS_KEY, v));

	const cfg = reactive({
		rpm: 1200, feed: 0.05, diam: 80, inner_diam: 0,
		sample_rate: 25000, duration_sec: 8, ppr: 1,
		drift_comp: false,   // optional drift compensation on the saved .mat/live_cache (raw stays raw)
		frm_from_cut: false, // when true, live FRM waits for cut detection — off by default for immediate feedback
	});
	const meta = reactive<Record<string, string>>({
		sample_name: 'SIM-CUT-001', sample_code: '', operation: '', op_type: '',
		insert: '', edge_id: '', coolant: '', notes: '',
	});
	// Extra machining fields mirroring the Directus manufacturing_operations form (folded section).
	const machining = reactive<{ axial_doc: string; radial_doc: string; cutting_length: string; coolant_pressure: string; operation_sequence: string; chips_ref: string; new_edge: boolean; chips_collected: boolean }>(
		{ axial_doc: '', radial_doc: '', cutting_length: '', coolant_pressure: '', operation_sequence: '', chips_ref: '', new_edge: false, chips_collected: false },
	);
	const plot = reactive<{ forceMode: 'time' | 'fft'; frmAxis: Axis; colormap: string; pointSize: number; windowSec: number; liveFrmStride: number }>({
		forceMode: 'time', frmAxis: 'Fz', colormap: 'viridis', pointSize: 1.8, windowSec: 12, liveFrmStride: 1,
	});
	watch(() => plot.windowSec, (v) => { client.windowSec = Math.max(1, v); });
	const replay = reactive<{ query: string; options: ReplayOption[]; cacheId: string; label: string; speed: number; loading: boolean }>(
		{ query: '', options: [], cacheId: '', label: '', speed: 20, loading: false },
	);

	const busy = ref(false);
	const errMsg = ref<string | null>(null);
	const finishedCache = shallowRef<Cache | null>(null);
	const st = client.status;
	const saveOpen = ref(false);

	// Directus links for the run write-back (2d)
	const link = reactive({
		sampleId: '', sampleLabel: '', operatorId: '', operatorLabel: '',
		equipmentId: '', equipmentLabel: '', insertId: '', insertLabel: '',
		edgeId: '', edgeLabel: '', toolId: '', toolLabel: '',
	});
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

	// Machine/Tool lookups narrow to whatever category the currently-selected Operation type
	// implies (turning/milling) — re-evaluated fresh on every keystroke, so changing Operation type
	// immediately re-scopes both without the user having to re-type their search.
	function searchEquipmentForOp(q: string) { return searchEquipment(q, opTypeCategory(meta.op_type)); }
	function searchToolsForOp(q: string) { return searchTools(q, opTypeCategory(meta.op_type)); }

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

	// Rough size estimate for the planned recording: raw float32 samples across all 10 columns
	// (Time + 8 dyno channels + Tacho), matching the backend's own estimate_recording_size_gb.
	// float32, NOT float64 — the raw writer emits dtype "<f4" (d1rw.py) and recovery.py reads
	// row_bytes = n_cols * 4. Assuming 8 bytes doubled every estimate, which tripped the
	// "not enough disk space" confirm below on runs that fit with room to spare.
	// Only meaningful when duration_sec reflects an actual plan — for real (nidaq) recordings it's
	// not enforced, just the number the user typed in as their target, which is exactly what's
	// needed here (and nowhere else currently uses it for nidaq).
	function estimatedRecordingGb(): number {
		return (cfg.sample_rate * cfg.duration_sec * RAW_COLUMNS * RAW_BYTES_PER_SAMPLE) / 1e9;
	}
	async function checkDiskBeforeStart(): Promise<boolean> {
		if (source.value === 'replay' || cfg.duration_sec <= 0) return true; // replay is short/bounded
		try {
			const res = await fetch(`${client.baseUrl}/storage/config`);
			if (!res.ok) return true; // can't check — don't block on it
			const info = await res.json();
			// free_gb is null when the backend could not stat the drive. Number(null) is 0, which
			// would read as "disk completely full" and prompt on every start — check for the null
			// explicitly and treat unknown as "can't check, don't block".
			if (info.free_gb == null) return true;
			const freeGb = Number(info.free_gb);
			if (!Number.isFinite(freeGb)) return true;
			const neededGb = estimatedRecordingGb();
			// Leave headroom: warn if the plan would eat into the last ~10% of what's free, not just
			// if it would exactly fill the disk — finalize() also needs room for capture.mat/live_cache.
			if (neededGb > freeGb * 0.9) {
				return confirm(
					`This recording is planned for ${cfg.duration_sec}s at ${cfg.sample_rate} Hz, which needs ` +
					`roughly ${neededGb.toFixed(1)} GB — but only ${freeGb.toFixed(1)} GB is free.\n\n` +
					`Continue anyway? The recording may be cut short if the disk fills up.`,
				);
			}
			return true;
		} catch { return true; } // backend unreachable — the normal start() error path will explain that
	}

	async function start() {
		if (busy.value) return;
		if (!(await checkDiskBeforeStart())) return;
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
				// Reset the charge amplifier before each cut (clears accumulated charge drift).
				try {
					await labamp.setMode('RESET');
					await new Promise((r) => setTimeout(r, 500));
					await labamp.setMode('MEASURE');
				} catch { /* amp unreachable — proceed anyway, gains were set at last range */ }
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
		// Open the save dialog the instant Stop is pressed (not once finalize finishes) — it shows a
		// loading state until st.state reaches 'done', so the user gets immediate feedback instead of
		// an interactive-looking-but-actually-stopped UI during the finalize gap.
		saveOpen.value = true;
		try {
			await client.stop();
			await loadFinished();
		} finally {
			busy.value = false;
			// The amp should only ever be in MEASURE while a cut is actually running — left in MEASURE
			// between cuts it keeps integrating charge drift for no reason. Best-effort: an unreachable
			// amp shouldn't block the UI from settling after stop.
			if (source.value === 'nidaq') labamp.setMode('RESET').catch(() => {});
		}
	}

	async function loadFinished() {
		const id = st.captureId;
		if (!id) return;
		// finalize() writes live_cache.bin before it ever publishes state=done, so by the time this
		// is called the file is already complete on disk - a failure here is a transient network
		// hiccup, not missing data. Retry a few times before giving up, so the save dialog's "loading
		// trace" spinner doesn't turn into a false "no data" state on the first blip.
		for (let attempt = 0; attempt < 4; attempt++) {
			try {
				const res = await fetch(client.cacheUrl(id));
				if (res.ok) { finishedCache.value = parseCache(await res.arrayBuffer()); return; }
			} catch { /* retry */ }
			if (attempt < 3) await new Promise((r) => setTimeout(r, 400 * (attempt + 1)));
		}
	}

	function newRun() { client.reset(); finishedCache.value = null; errMsg.value = null; logged.value = false; saveOpen.value = false; }

	// End-of-cut save/upload: pushes the manufacturing_operations row (bypassing the offline queue,
	// since we need its operation_id back synchronously to link machining_force_analysis), then
	// uploads the capture.mat + live_cache.bin as Directus files and links them into a new
	// machining_force_analysis row. Throws on failure (offline, validation, etc) so the save dialog
	// can surface the error and let the user retry or fall back to a local-only save.
	// Directus surfaces validation/constraint failures as a JSON body with an `errors[]` array; a
	// bare axios error.message is just "Request failed with status code 500" and tells the user
	// nothing actionable. Pull the real reason out when it's there.
	function directusErrorMessage(e: any): string {
		const status = e?.response?.status;
		const detail = e?.response?.data?.errors?.[0]?.message;
		if (status && detail) return `${status}: ${detail}`;
		if (status) return `${status}: ${e?.message || 'request failed'}`;
		return e?.message || String(e);
	}
	async function uploadFile(blob: Blob, filename: string): Promise<string> {
		const fd = new FormData();
		fd.append('file', blob, filename);
		try {
			const res = await api.post('/files', fd);
			return res.data.data.id;
		} catch (e: any) {
			throw new Error(`file upload (${filename}) failed - ${directusErrorMessage(e)}`);
		}
	}
	async function logRunSync(): Promise<string> {
		const payload = buildRunPayload();
		payload.method_id = await resolveMachiningMethodId(meta.op_type).catch(() => null);
		let res;
		try {
			res = await api.post('/items/manufacturing_operations', payload);
		} catch (e: any) {
			throw new Error(`logging the run failed - ${directusErrorMessage(e)}`);
		}
		const opId = res.data?.data?.operation_id;
		if (!opId) {
			// The insert reported success but didn't hand back the new row's id (e.g. a field
			// permission hiding operation_id on the response) - without it we can't link
			// machining_force_analysis, so fail loudly here rather than inserting a row with a
			// silently-missing FK (which is what was producing the opaque 500 further down).
			throw new Error('run was logged but the server did not return its operation_id - cannot link the capture');
		}
		logged.value = true;
		return opId;
	}
	async function uploadCutToDatabase(): Promise<string> {
		const id = st.captureId;
		if (!id) throw new Error('no capture id for this recording');
		const opId = await logRunSync();
		const [matBlob, cacheBlob] = await Promise.all([
			fetch(client.matUrl(id)).then((r) => { if (!r.ok) throw new Error('capture.mat fetch failed'); return r.blob(); }),
			fetch(client.cacheUrl(id)).then((r) => { if (!r.ok) throw new Error('live_cache.bin fetch failed'); return r.blob(); }),
		]);
		const [matFileId, cacheFileId] = await Promise.all([
			uploadFile(matBlob, `${id}.mat`),
			uploadFile(cacheBlob, `${id}_live_cache.bin`),
		]);
		const peaks = st.summary?.peaks;
		// ForceDashboard's chart reads its plot data from `series` (a JSONB min/max envelope), not
		// from live_cache_file — without this, upload "succeeds" (peaks/FRM all show up fine) but
		// the force/RPM charts render "no data" forever, since series is otherwise left null.
		const series = finishedCache.value ? buildSeriesEnvelope(finishedCache.value) : null;
		try {
		await api.post('/items/machining_force_analysis', {
			operation_id: opId,
			directus_files_id: matFileId,
			live_cache_file: cacheFileId,
			status: 'done',
			sample_rate: cfg.sample_rate,
			feed: cfg.feed,
			cut_diameter: cfg.diam,
			max_rpm: cfg.rpm,
			peak_fx: peaks?.Fx ?? null,
			peak_fy: peaks?.Fy ?? null,
			peak_fz: peaks?.Fz ?? null,
			series,
			matlab_version: 'force-app-direct',
			processed_at: new Date().toISOString(),
		});
		} catch (e: any) {
			throw new Error(`linking the capture failed - ${directusErrorMessage(e)} (the run was logged as operation ${opId}, and both files uploaded, but the analysis record could not be created)`);
		}
		return opId;
	}

	// Build + enqueue the manufacturing_operations run record (offline-queued in directusSync).
	function buildRunPayload(): Record<string, any> {
		const surface = Math.PI * cfg.diam * cfg.rpm / 1000;
		const num = (s: string) => (s !== '' && Number.isFinite(Number(s)) ? Number(s) : null);
		return {
			sample_id: link.sampleId || null,
			operator_person_id: link.operatorId || null,
			equipment_id: link.equipmentId || null,
			insert_edge_id: link.edgeId || null,
			tool_id: link.toolId || null,
			operation_date: new Date().toISOString(),
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

	// Auto-detect NI-DAQ hardware and switch source + channels if real devices are present — but
	// only ever as a first-run default. Re-checks localStorage fresh (not the `storedSource` value
	// captured above at workspace-creation time) immediately before applying, so a source picked
	// while this fetch was in flight always wins no matter which finishes first.
	(async () => {
		if (storedSource) return;
		try {
			const res = await fetch(`${client.baseUrl}/nidaq/devices`);
			if (!res.ok) return;
			const devs = await res.json();
			if (localStorage.getItem(SOURCE_LS_KEY)) return; // user chose explicitly while this was in flight
			if (!devs.simulated && devs.chassis?.length) {
				setSource('nidaq');
				// The amp should sit in RESET whenever we're not actively recording — cover the
				// "just found real hardware at app boot" case too, not only after a cut ends.
				labamp.setMode('RESET').catch(() => {});
				const ar = await fetch(`${client.baseUrl}/nidaq/channels/autoassign`, { method: 'POST' });
				if (ar.ok) {
					const data = await ar.json();
					const detected = (data.channels || []).map((c: any) => c.physical).join('\n');
					nidaqChannels.value = detected;
					localStorage.setItem(NIDAQ_LS_KEY, detected);
				}
			}
		} catch { /* backend unreachable — stay on sim */ }
	})();

	// Directus-backed cut picker for replay. Only `operation_id.pass_code` is set by the
	// MATLAB/crawler ingestion pipeline — a cut recorded and uploaded directly through force-app
	// (uploadCutToDatabase) never gets a pass_code, so it was both unsearchable (pass_code-only
	// filter can't match null) and effectively invisible in the unfiltered list (sorted by
	// pass_code, nulls last, past the 25-row limit) — i.e. "replay my last recording" could never
	// find a force-app-made recording at all. Fixed by also matching the linked sample's
	// code/nickname, and sorting by recency (this row's own created_at) instead of pass_code, so
	// the most recent recording — pass_code or not — is what shows up first with no search needed.
	// Also progressively narrowed by whatever Sample/Operation type/Machine are currently picked in
	// the metadata section above (all optional, AND-ed together) — so filling those in before
	// searching narrows straight to "operations on this sample, this type, this machine" instead of
	// free-text search being the only way in. Re-run (see the watch in RecordingOptions.vue)
	// whenever any of those three change while in replay mode.
	async function searchCuts(q: string) {
		replay.loading = true;
		try {
			const filter: any = { status: { _eq: 'done' }, live_cache_file: { _nnull: true } };
			const and: any[] = [];
			if (q && q.trim()) {
				const query = q.trim();
				and.push({ _or: [
					{ operation_id: { pass_code: { _icontains: query } } },
					{ operation_id: { sample_id: { sample_code: { _icontains: query } } } },
					{ operation_id: { sample_id: { nickname: { _icontains: query } } } },
				] });
			}
			if (link.sampleId) and.push({ operation_id: { sample_id: { _eq: link.sampleId } } });
			if (link.equipmentId) and.push({ operation_id: { equipment_id: { _eq: link.equipmentId } } });
			const category = opTypeCategory(meta.op_type);
			if (category) and.push({ operation_id: { machining_operation_subtype: { _starts_with: category === 'turning' ? 'MT' : 'MM' } } });
			if (and.length) filter._and = and;
			const res = await api.get('/items/machining_force_analysis', {
				params: {
					filter, limit: 25, sort: '-created_at',
					fields: ['id', 'live_cache_file', 'created_at', 'operation_id.operation_id', 'operation_id.pass_code',
						'operation_id.sample_id.sample_code', 'operation_id.sample_id.nickname'],
				},
			});
			replay.options = (res.data?.data ?? []).map((r: any) => ({
				label: r.operation_id?.pass_code || r.operation_id?.sample_id?.sample_code || r.operation_id?.sample_id?.nickname || r.id,
				cacheId: r.live_cache_file, opId: r.id, operationId: r.operation_id?.operation_id ?? null,
			})).filter((o: ReplayOption) => o.cacheId);
		} catch { replay.options = []; } finally { replay.loading = false; }
	}

	// Picking a cut to replay loads that operation's FULL original metadata into the same fields a
	// live/sim recording would use — previously only the sample name got copied, so "rerun a past
	// recording" left every other field (operator, machine, tool, insert/edge, machining params)
	// blank even though the original operation had them all recorded.
	async function pickReplayCut(o: ReplayOption) {
		replay.cacheId = o.cacheId; replay.label = o.label;
		if (!o.operationId) return;
		try {
			const res = await api.get(`/items/manufacturing_operations/${o.operationId}`, {
				params: { fields: ['*',
					'sample_id.sample_id', 'sample_id.sample_code', 'sample_id.nickname',
					'operator_person_id.person_id', 'operator_person_id.full_name',
					'equipment_id.equipment_id', 'equipment_id.equipment_name',
					'tool_id.tool_id', 'tool_id.tool_code', 'tool_id.tool_name',
					'insert_edge_id.edge_id', 'insert_edge_id.edge_code',
					'insert_edge_id.insert_id.insert_id', 'insert_edge_id.insert_id.insert_code',
				] },
			});
			const d = res.data?.data;
			if (!d) return;
			const rm = d.recorded_metadata || {};
			link.sampleId = d.sample_id?.sample_id || ''; link.sampleLabel = d.sample_id?.sample_code || d.sample_id?.nickname || '';
			link.operatorId = d.operator_person_id?.person_id || ''; link.operatorLabel = d.operator_person_id?.full_name || '';
			link.equipmentId = d.equipment_id?.equipment_id || ''; link.equipmentLabel = d.equipment_id?.equipment_name || '';
			link.toolId = d.tool_id?.tool_id || ''; link.toolLabel = d.tool_id?.tool_code || d.tool_id?.tool_name || '';
			link.insertId = d.insert_edge_id?.insert_id?.insert_id || ''; link.insertLabel = d.insert_edge_id?.insert_id?.insert_code || '';
			link.edgeId = d.insert_edge_id?.edge_id || ''; link.edgeLabel = d.insert_edge_id?.edge_code || '';
			meta.op_type = d.machining_operation_subtype || '';
			meta.sample_name = rm.sample_name || link.sampleLabel || o.label;
			meta.coolant = rm.coolant || '';
			meta.notes = d.outcome_notes || rm.notes || '';
			machining.axial_doc = d.machining_axial_depth_of_cut_mm != null ? String(d.machining_axial_depth_of_cut_mm) : '';
			machining.radial_doc = d.machining_radial_depth_of_cut_mm != null ? String(d.machining_radial_depth_of_cut_mm) : '';
			machining.cutting_length = d.machining_cutting_length_mm != null ? String(d.machining_cutting_length_mm) : '';
			machining.coolant_pressure = d.machining_coolant_pressure_bar != null ? String(d.machining_coolant_pressure_bar) : '';
			machining.operation_sequence = d.operation_sequence != null ? String(d.operation_sequence) : '';
			machining.chips_ref = d.machining_chips_ref_code || '';
			machining.new_edge = !!d.machining_new_edge;
			machining.chips_collected = !!d.machining_chips_collected;
		} catch { /* best-effort — the cut is still replayable even if metadata hydration fails */ }
	}

	return {
		client, source, setSource, nidaqChannels, cfg, meta, machining, plot, replay, st, busy, errMsg, finishedCache,
		isIdle, isRecording, isFinalizing, isDone, locked, saveOpen,
		start, stop, newRun, loadFinished, searchCuts, pickReplayCut, metaObj, uploadCutToDatabase,
		// 2d: Directus links + run write-back
		link, logged, onSelectSample, logRunNow, syncStatus,
		searchSamples, searchOperators, searchEquipment, searchToolsForOp, searchEquipmentForOp, searchInserts, searchEdges,
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
