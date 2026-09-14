<script setup lang="ts">
// Files a GitHub issue directly from inside the app. The backend holds the GitHub token (see
// backend/app/bug_report.py) — this form only ever talks to our own recorder backend, never to
// GitHub directly, so no credential of any kind lives in the renderer.
import { onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { getConfig } from '../config';
import { authStore } from '../authStore';
import { getConsoleTail } from '../clientLog';

const base = () => getConfig().recorderUrl;
const route = useRoute();

const configured = ref<boolean | null>(null); // null = still checking
const kind = ref<'bug' | 'feature'>('bug');
const title = ref('');
const description = ref('');
const includeLogs = ref(true);
const submitting = ref(false);
const result = ref<{ ok: boolean; url?: string; reason?: string } | null>(null);
const appVersion = ref('');

onMounted(() => {
	// Independent requests — run them concurrently rather than one-after-the-other.
	const statusP = fetch(`${base()}/support/report-bug`)
		.then((res) => res.json())
		.then((data) => { configured.value = !!data.configured; })
		.catch(() => { configured.value = false; });
	const versionP = window.forceApp
		? window.forceApp.getUpdateInfo()
			.then((info) => { appVersion.value = info.version; })
			.catch(() => { /* browser-served build or bridge unavailable — version stays blank */ })
		: Promise.resolve();
	return Promise.all([statusP, versionP]);
});

async function submit() {
	if (!title.value.trim() || submitting.value) return;
	submitting.value = true;
	result.value = null;
	try {
		const body = new URLSearchParams({
			title: title.value.trim(),
			description: description.value.trim(),
			app_version: appVersion.value,
			platform: navigator.platform || '',
			route: route.fullPath,
			reporter_email: authStore.currentUser.value?.email || '',
			include_logs: String(includeLogs.value),
			kind: kind.value,
			// Gated on the same checkbox as the backend log: both are diagnostic attachments, and
			// an operator who declines to attach logs has not agreed to send their console either.
			console_tail: includeLogs.value ? getConsoleTail() : '',
		});
		const res = await fetch(`${base()}/support/report-bug`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
			body,
		});
		const data = await res.json();
		result.value = data;
		if (data.ok) {
			title.value = '';
			description.value = '';
		}
	} catch (e: any) {
		result.value = { ok: false, reason: e?.message || "couldn't reach the recording backend" };
	} finally {
		submitting.value = false;
	}
}
</script>

<template>
	<div class="report">
		<h2>Report a bug or request a feature</h2>
		<p class="lead">
			Opens an issue directly on the project's GitHub, with your description plus the app version,
			current page, and (optionally) a tail of the recent backend log — the same log Settings > Logs
			shows.
		</p>

		<div v-if="configured === false" class="warnbox">
			<span class="material-symbols-rounded">warning</span>
			<div>
				<b>Not configured on this machine</b>
				<span>This install has no GitHub token set for filing reports. Describe the bug to whoever
					manages this app's deployment, or attach a Settings &gt; Logs export manually.</span>
			</div>
		</div>

		<template v-else>
			<div class="kindpick" role="radiogroup" aria-label="Report type">
				<button type="button" class="kindbtn" :class="{ on: kind === 'bug' }" role="radio" :aria-checked="kind === 'bug'"
					:disabled="submitting" @click="kind = 'bug'">
					<span class="material-symbols-rounded">bug_report</span> Bug
				</button>
				<button type="button" class="kindbtn" :class="{ on: kind === 'feature' }" role="radio" :aria-checked="kind === 'feature'"
					:disabled="submitting" @click="kind = 'feature'">
					<span class="material-symbols-rounded">lightbulb</span> Feature request
				</button>
			</div>
			<label class="field">
				<span>Title</span>
				<input v-model="title" :placeholder="kind === 'bug' ? 'short summary of what went wrong' : 'short summary of what you\'d like to see'" maxlength="250" :disabled="submitting" />
			</label>
			<label class="field">
				<span>{{ kind === 'bug' ? 'What happened?' : 'What would you like?' }}</span>
				<textarea v-model="description" rows="6"
					:placeholder="kind === 'bug' ? 'what you did, what you expected, what happened instead…' : 'what you want, and why it would help…'"
					:disabled="submitting"></textarea>
			</label>
			<label class="chk">
				<input type="checkbox" v-model="includeLogs" :disabled="submitting" />
				Include diagnostics: recent backend log, this window's console, and machine state
				(amp mode, NI-DAQ devices, channel map, disk space). Helps a lot — no personal data
				beyond your login email, which is included separately below.
			</label>

			<button class="btn save" :disabled="!title.trim() || submitting || configured === null" @click="submit">
				<span class="material-symbols-rounded">{{ submitting ? 'hourglass_top' : (kind === 'bug' ? 'bug_report' : 'lightbulb') }}</span>
				{{ submitting ? 'Filing…' : (kind === 'bug' ? 'File bug report' : 'File feature request') }}
			</button>

			<p v-if="result?.ok" class="ok">
				<span class="material-symbols-rounded">check_circle</span>
				Filed as <a :href="result.url" target="_blank" rel="noopener">issue #{{ (result as any).number ?? '' }}</a>.
			</p>
			<p v-else-if="result && !result.ok" class="err">
				<span class="material-symbols-rounded">error</span>{{ result.reason }}
			</p>
		</template>
	</div>
</template>

<style scoped>
.report { max-width: 640px; }
h2 { margin: 0 0 4px; font-size: 16px; }
.lead { margin: 0 0 18px; font-size: 13px; color: var(--text-dim); line-height: 1.5; }
.warnbox { display: flex; gap: 10px; padding: 11px 13px; margin-bottom: 14px; font-size: 12.5px;
	background: rgba(251,191,36,0.08); border: 1px solid rgba(251,191,36,0.3); border-radius: 9px; }
.warnbox .material-symbols-rounded { font-size: 20px; color: #fbbf24; }
.warnbox div { display: flex; flex-direction: column; gap: 2px; }
.warnbox b { font-size: 13px; }
.warnbox span { color: var(--text-dim); line-height: 1.45; }

.kindpick { display: flex; gap: 8px; margin-bottom: 16px; }
.kindbtn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; font-size: 12.5px; font-weight: 600;
	color: var(--text-dim); background: var(--surface); border: 1px solid var(--border); border-radius: 8px; cursor: pointer; }
.kindbtn .material-symbols-rounded { font-size: 17px; }
.kindbtn.on { color: var(--accent-ink); background: var(--accent); border-color: var(--accent); }
.kindbtn:disabled { opacity: 0.5; cursor: not-allowed; }

.field { display: flex; flex-direction: column; gap: 5px; font-size: 12.5px; color: var(--text-dim); margin-bottom: 14px; }
.field input, .field textarea { padding: 9px 11px; font: inherit; font-size: 13px; color: var(--text);
	background: var(--surface); border: 1px solid var(--border); border-radius: 8px; outline: none; resize: vertical; }
.field input:focus, .field textarea:focus { border-color: var(--accent); }

.chk { display: flex; align-items: flex-start; gap: 8px; font-size: 12.5px; color: var(--text); cursor: pointer; margin-bottom: 16px; line-height: 1.4; }
.chk input { accent-color: var(--accent); margin-top: 2px; }

.btn { display: inline-flex; align-items: center; gap: 6px; padding: 9px 16px; font-size: 13px; font-weight: 600; border: none; border-radius: 8px; cursor: pointer; }
.btn.save { background: var(--accent); color: var(--accent-ink); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }

.ok { display: flex; align-items: center; gap: 5px; color: #4ade80; font-size: 12.5px; margin-top: 10px; }
.ok a { color: inherit; text-decoration: underline; }
.err { display: flex; align-items: center; gap: 5px; color: var(--danger); font-size: 12.5px; margin-top: 10px; }
</style>
