<script setup lang="ts">
import { nextTick, ref } from 'vue';
import { useApi } from '@directus/extensions-sdk';
import ChartPanel from './chart-panel.vue';

interface ChartSpec {
	type: 'bar' | 'line' | 'scatter' | 'histogram' | 'pie';
	x: string;
	y: string[];
	title?: string;
}

interface Turn {
	question: string;
	status: 'pending' | 'done' | 'error';
	sql?: string;
	columns?: string[];
	rows?: Record<string, unknown>[];
	chart?: ChartSpec | null;
	reply?: string | null;
	error?: string;
}

const api = useApi();
const input = ref('');
const turns = ref<Turn[]>([]);
const scroller = ref<HTMLDivElement | null>(null);

const busy = () => turns.value.some((t) => t.status === 'pending');

/** Prior completed turns become conversation context so follow-ups can refine. */
function history(): { role: string; content: string }[] {
	const msgs: { role: string; content: string }[] = [];
	for (const t of turns.value) {
		if (t.status !== 'done') continue;
		msgs.push({ role: 'user', content: t.question });
		if (t.sql) msgs.push({ role: 'assistant', content: t.sql });
	}
	return msgs;
}

async function scrollToEnd() {
	await nextTick();
	scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' });
}

async function submit() {
	const question = input.value.trim();
	if (!question || busy()) return;

	const messages = [...history(), { role: 'user', content: question }];
	const turn = ref<Turn>({ question, status: 'pending' }).value;
	turns.value.push(turn);
	input.value = '';
	await scrollToEnd();

	try {
		const { data } = await api.post('/d1-ask/chat', { messages });
		turn.reply = data.reply ?? null;
		turn.sql = data.sql;
		turn.columns = data.columns ?? [];
		turn.rows = data.rows ?? [];
		turn.chart = data.chart ?? null;
		turn.status = 'done';
	} catch (err: any) {
		const d = err?.response?.data;
		turn.status = 'error';
		if (d?.sql) turn.sql = d.sql;
		if (d?.error && d?.reason) {
			// Guard rejection or a query that couldn't run — show why + the SQL.
			turn.error = `${d.error}: ${d.reason}. Try rephrasing.`;
		} else {
			turn.error = d?.error || err?.message || 'The request failed.';
		}
	}
	await scrollToEnd();
}

function cell(value: unknown): string {
	if (value === null || value === undefined) return '';
	if (typeof value === 'object') return JSON.stringify(value);
	return String(value);
}
</script>

<template>
	<private-view title="Ask the Database">
		<div class="ask-db">
			<div ref="scroller" class="transcript">
				<p v-if="turns.length === 0" class="hint">
					Ask a question about your lab data in plain English — for example
					“how many samples per material?” or “average tensile strength by
					alloy”. Answers run as guarded, read-only queries; follow-up questions
					refine the previous one.
				</p>

				<div v-for="(turn, i) in turns" :key="i" class="turn">
					<div class="question">{{ turn.question }}</div>

					<div v-if="turn.status === 'pending'" class="pending">Thinking…</div>

					<div v-else-if="turn.status === 'error'" class="answer error">
						<p>{{ turn.error }}</p>
						<details v-if="turn.sql" data-test="ask-sql">
							<summary>Rejected SQL</summary>
							<pre>{{ turn.sql }}</pre>
						</details>
					</div>

					<!-- A plain conversational reply (greeting / off-topic): no table. -->
					<div v-else-if="turn.reply" class="answer">
						<p class="reply" data-test="ask-reply">{{ turn.reply }}</p>
					</div>

					<div v-else class="answer">
						<details v-if="turn.sql" class="sql" data-test="ask-sql">
							<summary>SQL</summary>
							<pre>{{ turn.sql }}</pre>
						</details>

						<ChartPanel
							v-if="turn.chart && turn.rows && turn.rows.length"
							:spec="turn.chart"
							:rows="turn.rows"
						/>

						<div class="table-wrap" data-test="ask-table">
							<p v-if="!turn.rows || turn.rows.length === 0" class="hint">
								No rows.
							</p>
							<table v-else>
								<thead>
									<tr>
										<th v-for="col in turn.columns" :key="col">{{ col }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="(row, r) in turn.rows" :key="r">
										<td v-for="col in turn.columns" :key="col">
											{{ cell(row[col]) }}
										</td>
									</tr>
								</tbody>
							</table>
						</div>
					</div>
				</div>
			</div>

			<form class="composer" @submit.prevent="submit">
				<input
					v-model="input"
					data-test="ask-input"
					type="text"
					placeholder="Ask a question about your data…"
					:disabled="busy()"
					autocomplete="off"
				/>
				<button data-test="ask-submit" type="submit" :disabled="busy() || !input.trim()">
					Ask
				</button>
			</form>
		</div>
	</private-view>
</template>

<style scoped>
.ask-db {
	display: flex;
	flex-direction: column;
	height: calc(100vh - 60px);
	padding: 0 32px 24px;
	max-width: 1100px;
}
.transcript {
	flex: 1;
	overflow-y: auto;
	padding: 16px 0;
}
.hint {
	color: var(--theme--foreground-subdued, #6c7789);
}
.turn {
	margin-bottom: 28px;
}
.question {
	font-weight: 600;
	font-size: 16px;
	margin-bottom: 10px;
	color: var(--theme--foreground, #2f3a4c);
}
.pending {
	color: var(--theme--foreground-subdued, #6c7789);
	font-style: italic;
}
.answer.error p {
	color: var(--theme--danger, #e35169);
}
.sql summary {
	cursor: pointer;
	color: var(--theme--foreground-subdued, #6c7789);
}
pre {
	background: var(--theme--background-subdued, #f4f5f7);
	padding: 12px;
	border-radius: 6px;
	overflow-x: auto;
	font-size: 13px;
}
.table-wrap {
	margin-top: 12px;
	overflow-x: auto;
	border: 1px solid var(--theme--border-color-subdued, #e0e2e7);
	border-radius: 6px;
}
table {
	border-collapse: collapse;
	width: 100%;
	font-size: 13px;
}
th,
td {
	text-align: left;
	padding: 8px 12px;
	border-bottom: 1px solid var(--theme--border-color-subdued, #e0e2e7);
	white-space: nowrap;
}
th {
	background: var(--theme--background-subdued, #f4f5f7);
	font-weight: 600;
}
.composer {
	display: flex;
	gap: 8px;
	padding-top: 12px;
	border-top: 1px solid var(--theme--border-color-subdued, #e0e2e7);
}
.composer input {
	flex: 1;
	padding: 10px 14px;
	border: 2px solid var(--theme--border-color, #d3dae4);
	border-radius: 8px;
	font-size: 15px;
	background: var(--theme--background, #fff);
	color: var(--theme--foreground, #2f3a4c);
}
.composer input:focus {
	outline: none;
	border-color: var(--theme--primary, #6644ff);
}
.composer button {
	padding: 10px 22px;
	border: none;
	border-radius: 8px;
	background: var(--theme--primary, #6644ff);
	color: #fff;
	font-weight: 600;
	cursor: pointer;
}
.composer button:disabled {
	opacity: 0.5;
	cursor: not-allowed;
}
</style>
