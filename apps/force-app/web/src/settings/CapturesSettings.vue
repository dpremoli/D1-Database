<script setup lang="ts">
// Local capture housekeeping. Captures accumulate on the recording drive indefinitely: "Don't
// save" deliberately leaves the raw on disk, and recovery.discard_session refuses to touch
// finalized sessions — so until now nothing in the app could show what was there, let alone
// remove it. This lists everything with sizes and upload state, and can delete or re-upload.
import { computed, onMounted, ref } from 'vue';
import { getConfig } from '../config';
import { api } from '../directusClient';
import { uploadCaptureColdStart } from '../record/uploadCapture';
import { discardQueued, listQueue, retryQueued, syncStatus, type QueuedRun } from '../record/directusSync';

interface Capture {
	id: string;
	size_mb: number;
	finalized: boolean;
	files: Record<string, number>;
	mtime: number;
	sample_name?: string;
	duration_sec?: number;
	n?: number;
	peaks?: { Fx: number; Fy: number; Fz: number };
	source?: string;
}

const base = () => getConfig().recorderUrl;

const captures = ref<Capture[]>([]);
const capturesRoot = ref('');
const totalMb = ref(0);
const disk = ref<{ free_gb?: number; total_gb?: number }>({});
const loading = ref(false);
const error = ref('');
const busy = ref<Record<string, string>>({});   // id -> 'deleting' | 'uploading'
const rowMsg = ref<Record<string, string>>({});
// Which captures already exist in Directus. Looked up once per load so the list can distinguish
// "safe to delete, it's in the database" from "this is the only copy".
const uploaded = ref<Record<string, boolean>>({});
const uploadedKnown = ref(false);

async function load() {
	loading.value = true;
	error.value = '';
	try {
		const res = await fetch(`${base()}/captures/browse?limit=500`);
		if (!res.ok) throw new Error(`HTTP ${res.status}`);
		const data = await res.json();
		captures.value = data.captures || [];
		capturesRoot.value = data.captures_root || '';
		totalMb.value = data.total_size_mb || 0;
		disk.value = data.disk || {};
		void checkUploaded();
	} catch (e: any) {
		error.value = /failed to fetch|load failed|networkerror/i.test(e?.message || '')
			? "can't reach the recording backend — is it running?"
			: e?.message || 'failed to list captures';
	} finally {
		loading.value = false;
	}
}

async function checkUploaded() {
	// recorded_metadata.capture_id is what both upload paths stamp (workspace.ts and
	// uploadCapture.ts), so it is the link back from a local capture to its database row.
	uploadedKnown.value = false;
	try {
		const ids = captures.value.map((c) => c.id);
		if (!ids.length) { uploadedKnown.value = true; return; }
		const res = await api.get('/items/manufacturing_operations', {
			params: {
				filter: { recorded_metadata: { capture_id: { _in: ids } } },
				fields: ['recorded_metadata'], limit: -1,
			},
		});
		const found: Record<string, boolean> = {};
		for (const row of res.data?.data ?? []) {
			const cid = row?.recorded_metadata?.capture_id;
			if (cid) found[cid] = true;
		}
		uploaded.value = found;
		uploadedKnown.value = true;
	} catch {
		// Offline or not permitted — leave the state unknown rather than claiming "not uploaded",
		// which would invite deleting the only copy of a capture that is in fact safe.
		uploadedKnown.value = false;
	}
}

async function remove(c: Capture) {
	const known = uploadedKnown.value;
	const isUp = !!uploaded.value[c.id];
	const warning = isUp
		? 'It has been uploaded to the database, so the analysis record will remain.'
		: known
			? 'It has NOT been uploaded — this is the only copy and it cannot be recovered.'
			: "Its upload status is unknown (the database is unreachable), so this may be the only copy.";
	if (!confirm(`Delete ${c.sample_name || c.id}? (${fmtSize(c.size_mb)})\n\n${warning}\n\nThis cannot be undone.`)) return;
	busy.value[c.id] = 'deleting';
	rowMsg.value[c.id] = '';
	try {
		const res = await fetch(`${base()}/captures/${c.id}`, { method: 'DELETE' });
		if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.detail || `HTTP ${res.status}`);
		captures.value = captures.value.filter((x) => x.id !== c.id);
		totalMb.value = Math.max(0, Number((totalMb.value - c.size_mb).toFixed(2)));
	} catch (e: any) {
		rowMsg.value[c.id] = `delete failed: ${e?.message || e}`;
	} finally {
		delete busy.value[c.id];
	}
}

async function upload(c: Capture) {
	busy.value[c.id] = 'uploading';
	rowMsg.value[c.id] = '';
	try {
		const sum = await fetch(`${base()}/captures/${c.id}/summary`).then((r) => {
			if (!r.ok) throw new Error(`summary: HTTP ${r.status}`);
			return r.json();
		});
		await uploadCaptureColdStart({
			captureId: c.id,
			matUrl: `${base()}/captures/${c.id}/capture.mat`,
			cacheUrl: `${base()}/captures/${c.id}/live_cache.bin`,
			cfg: sum.config || {},
			peaks: sum.peaks,
		});
		uploaded.value = { ...uploaded.value, [c.id]: true };
		rowMsg.value[c.id] = 'uploaded';
	} catch (e: any) {
		rowMsg.value[c.id] = `upload failed: ${e?.message || e}`;
	} finally {
		delete busy.value[c.id];
	}
}

async function uploadAllUnsynced() {
	const pending = unsynced.value.slice();
	if (!pending.length) return;
	if (!confirm(`Upload ${pending.length} capture${pending.length === 1 ? '' : 's'} to the database?`)) return;
	for (const c of pending) await upload(c);   // sequential: each is a multi-MB file upload
}


function fmtSize(mb: number): string {
	if (mb < 1) return `${(mb * 1000).toFixed(0)} KB`;
	if (mb < 1000) return `${mb.toFixed(1)} MB`;
	return `${(mb / 1000).toFixed(2)} GB`;
}
function fmtDate(mtime: number): string {
	if (!mtime) return '—';
	return new Date(mtime * 1000).toLocaleString();
}

// ---- Pending run-record uploads ----
// The offline queue (directusSync) retries in the background, but a permanent failure — a
// validation or permission error — parks an item forever behind a topbar count with no way to see
// which run, why, or to clear it. flush() also stops at the first such failure, so one poisoned
// item blocks everything behind it.
const queue = ref<QueuedRun[]>([]);
const queueBusy = ref<string | null>(null);
function refreshQueue() { queue.value = listQueue(); }

// uploadCaptureColdStart has no idempotency guard: running it twice creates a SECOND
// manufacturing_operations row plus a second analysis record, and re-sends the multi-MB files. So
// an upload is only offered when we positively know one hasn't happened. Two states must suppress
// it — an unknown upload state (Directus unreachable, so `uploaded` is empty, which is NOT the
// same as "nothing is uploaded"), and a run still in the offline queue, which will be written by
// itself as soon as the connection returns.
const queuedCaptureIds = computed(
	() => new Set(queue.value.map((q) => q.payload?.recorded_metadata?.capture_id).filter(Boolean)),
);
function canUpload(c: Capture): boolean {
	return c.finalized && uploadedKnown.value
		&& !uploaded.value[c.id] && !queuedCaptureIds.value.has(c.id);
}
const unsynced = computed(() => captures.value.filter(canUpload));

async function retryOne(id: string) {
	queueBusy.value = id;
	try {
		// false = a background sync already held the lock, so nothing was attempted now. Say so
		// rather than letting the row look as though it had been retried and failed again.
		const attempted = await retryQueued(id);
		if (!attempted) rowMsg.value[id] = 'a sync is already running — this run is next in line';
	} finally { queueBusy.value = null; refreshQueue(); }
}
function discardOne(item: QueuedRun) {
	const name = item.payload?.recorded_metadata?.sample_name || item.payload?.recorded_metadata?.capture_id || item.id;
	if (!confirm(`Discard the queued database record for ${name}?\n\nThe recording itself stays on disk — only the pending database write is abandoned.`)) return;
	discardQueued(item.id);
	refreshQueue();
}
function queueLabel(item: QueuedRun): string {
	const rm = item.payload?.recorded_metadata || {};
	return rm.sample_name || rm.capture_id || item.collection;
}

onMounted(() => { load(); refreshQueue(); });
</script>

<template>
	<div class="caps">
		<h2>Local Captures</h2>
		<p class="lead">
			Every recording stored on this machine. Recordings stay on disk even when you choose not to
			save them, so this is where to reclaim space — and to re-upload anything that never made it
			to the database.
		</p>

		<div class="summary">
			<div class="stat"><span>Captures</span><b>{{ captures.length }}</b></div>
			<div class="stat"><span>Using</span><b>{{ fmtSize(totalMb) }}</b></div>
			<div class="stat" v-if="disk.free_gb != null">
				<span>Free on drive</span><b>{{ disk.free_gb.toFixed(1) }} GB</b>
			</div>
			<div class="spacer"></div>
			<button class="btn ghost" :disabled="loading" @click="load">
				<span class="material-symbols-rounded">{{ loading ? 'hourglass_top' : 'refresh' }}</span>
				{{ loading ? 'Loading…' : 'Refresh' }}
			</button>
			<button v-if="unsynced.length" class="btn save" @click="uploadAllUnsynced">
				<span class="material-symbols-rounded">cloud_upload</span>
				Upload {{ unsynced.length }} unsynced
			</button>
		</div>
		<p class="hint path" v-if="capturesRoot">{{ capturesRoot }}</p>

		<p v-if="error" class="err">{{ error }}</p>

		<!-- Pending run-record writes. Hidden entirely when the queue is empty, which is the
			 normal state — this only needs to exist when something is actually stuck. -->
		<template v-if="queue.length">
			<h3>Pending database records <span class="chip">{{ queue.length }}</span></h3>
			<p class="hint sub">
				Run records waiting to be written to the database. These retry automatically; an item with
				an error needs attention, and blocks the ones behind it until it is retried or discarded.
			</p>
			<div v-for="item in queue" :key="item.id" class="row qrow">
				<div class="rmain">
					<div class="rtop">
						<span class="rname">{{ queueLabel(item) }}</span>
						<span v-if="item.lastError" class="tag warn">error</span>
						<span v-else class="tag">queued</span>
					</div>
					<div class="rsub">
						<span>{{ item.collection }}</span>
						<span v-if="item.attempts">{{ item.attempts }} attempt<span v-if="item.attempts !== 1">s</span></span>
						<span>{{ new Date(item.createdAt).toLocaleString() }}</span>
					</div>
					<p v-if="rowMsg[item.id]" class="rmsg">{{ rowMsg[item.id] }}</p>
					<p v-if="item.lastError" class="rmsg bad">{{ item.lastError }}</p>
				</div>
				<div class="ract">
					<button class="btn ghost sm" :disabled="queueBusy === item.id" @click="retryOne(item.id)">
						<span class="material-symbols-rounded">{{ queueBusy === item.id ? 'hourglass_top' : 'refresh' }}</span>
						{{ queueBusy === item.id ? 'Retrying…' : 'Retry' }}
					</button>
					<button class="btn danger sm" :disabled="queueBusy === item.id" @click="discardOne(item)">
						<span class="material-symbols-rounded">delete</span>Discard
					</button>
				</div>
			</div>
			<p v-if="syncStatus.lastError" class="err">{{ syncStatus.lastError }}</p>
			<h3>Recordings on disk</h3>
		</template>

		<div v-if="!loading && !captures.length" class="empty">No recordings on this machine.</div>

		<div v-for="c in captures" :key="c.id" class="row">
			<div class="rmain">
				<div class="rtop">
					<span class="rname">{{ c.sample_name || c.id }}</span>
					<span v-if="!c.finalized" class="tag warn" title="No summary.json — this recording was never finalized">incomplete</span>
					<span v-else-if="!uploadedKnown" class="tag">upload state unknown</span>
					<span v-else-if="uploaded[c.id]" class="tag ok">uploaded</span>
					<span v-else-if="queuedCaptureIds.has(c.id)" class="tag">upload queued</span>
					<span v-else class="tag warn">not uploaded</span>
					<span v-if="c.source" class="tag dim">{{ c.source }}</span>
				</div>
				<div class="rsub">
					<span class="mono">{{ c.id }}</span>
					<span>{{ fmtSize(c.size_mb) }}</span>
					<span v-if="c.duration_sec != null">{{ c.duration_sec.toFixed(1) }}s</span>
					<span v-if="c.n">{{ c.n.toLocaleString() }} samples</span>
					<span>{{ fmtDate(c.mtime) }}</span>
				</div>
				<p v-if="rowMsg[c.id]" class="rmsg" :class="{ bad: rowMsg[c.id].includes('failed') }">{{ rowMsg[c.id] }}</p>
			</div>
			<div class="ract">
				<button v-if="canUpload(c)" class="btn ghost sm" :disabled="!!busy[c.id]" @click="upload(c)">
					<span class="material-symbols-rounded">{{ busy[c.id] === 'uploading' ? 'hourglass_top' : 'cloud_upload' }}</span>
					{{ busy[c.id] === 'uploading' ? 'Uploading…' : 'Upload' }}
				</button>
				<button class="btn danger sm" :disabled="!!busy[c.id]" @click="remove(c)">
					<span class="material-symbols-rounded">{{ busy[c.id] === 'deleting' ? 'hourglass_top' : 'delete' }}</span>
					{{ busy[c.id] === 'deleting' ? 'Deleting…' : 'Delete' }}
				</button>
			</div>
		</div>
	</div>
</template>

<style scoped>
.caps { max-width: 820px; }
h2 { margin: 0 0 4px; font-size: 16px; }
.lead { margin: 0 0 18px; font-size: 13px; color: var(--text-dim); line-height: 1.5; }
.hint { font-size: 11.5px; color: var(--text-dim); }
.path { margin: 6px 0 14px; font-family: var(--mono); word-break: break-all; }
.err { color: var(--danger); font-size: 12px; }
.summary { display: flex; align-items: flex-end; gap: 22px; padding: 12px 14px;
	background: var(--surface); border: 1px solid var(--border); border-radius: 10px; flex-wrap: wrap; }
.stat { display: flex; flex-direction: column; gap: 2px; }
.stat span { font-size: 11px; color: var(--text-dim); }
.stat b { font-size: 15px; font-variant-numeric: tabular-nums; }
.spacer { flex: 1; }
.btn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; font-size: 12.5px;
	font-weight: 600; border: none; border-radius: 8px; cursor: pointer; }
.btn.sm { padding: 6px 11px; font-size: 12px; }
.btn .material-symbols-rounded { font-size: 16px; }
.btn.ghost { background: var(--surface); color: var(--text); border: 1px solid var(--border); }
.btn.save { background: var(--accent); color: var(--accent-ink); }
.btn.danger { background: transparent; color: var(--danger); border: 1px solid var(--border); }
.btn.danger:hover:not(:disabled) { background: rgba(239,68,68,0.1); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.row { display: flex; align-items: center; gap: 12px; padding: 11px 13px; margin-top: 8px;
	background: var(--surface); border: 1px solid var(--border); border-radius: 10px; }
.rmain { flex: 1; min-width: 0; }
.rtop { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.rname { font-size: 13.5px; font-weight: 600; }
.rsub { display: flex; gap: 12px; margin-top: 3px; font-size: 11.5px; color: var(--text-dim);
	flex-wrap: wrap; font-variant-numeric: tabular-nums; }
.mono { font-family: var(--mono); }
.tag { font-size: 9.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.03em;
	padding: 1px 7px; border-radius: 99px; color: var(--text-dim); background: var(--surface-2); }
.tag.ok { color: #4ade80; background: rgba(74,222,128,0.12); }
.tag.warn { color: #fbbf24; background: rgba(251,191,36,0.14); }
.tag.dim { opacity: 0.7; }
.ract { display: flex; gap: 7px; flex-shrink: 0; }
.rmsg { margin: 5px 0 0; font-size: 11.5px; color: #4ade80; }
.rmsg.bad { color: var(--danger); }
.empty { padding: 26px; text-align: center; color: var(--text-dim); font-size: 12.5px;
	border: 1px dashed var(--border); border-radius: 10px; margin-top: 10px; }
h3 { margin: 24px 0 4px; font-size: 14px; display: flex; align-items: center; gap: 8px; }
.chip { font-size: 10px; font-weight: 700; color: var(--accent-ink); background: var(--accent);
	padding: 1px 7px; border-radius: 99px; }
.sub { margin: 0 0 8px; line-height: 1.45; }
.qrow { border-color: rgba(251,191,36,0.28); }
</style>
