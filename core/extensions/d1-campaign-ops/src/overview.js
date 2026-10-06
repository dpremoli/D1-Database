// Pure roll-up logic for the campaign overview panel (no Vue, no network), so it can be unit
// tested with `node --test core/extensions/d1-campaign-ops/index.test.mjs`.
//
// Inputs are the rows the panel reads through the Directus API (so the user's permissions already
// applied): the campaign_samples junction, the campaign's operations, its test sessions and the
// machining_force_analysis rows of those operations. Design:
// docs/superpowers/specs/2026-10-06-sample-timeline-and-campaign-overview-design.md

const worst = (s) => ['error', 'processing', 'pending'].find((k) => s.includes(k));

// One operation can have several force files (one machining_force_analysis row each). Roll the rows
// up to one state, worst first: error > processing > pending > done > skipped, 'none' when no rows.
export function analysisState(rows) {
	const s = (rows ?? []).map((r) => r?.status).filter(Boolean);
	if (!s.length) return 'none';
	return worst(s) ?? (s.includes('done') ? 'done' : 'skipped');
}

// Same for the Diagnostics build (`diag_status`, null until someone requests a build). Rows with no
// diag_status are ignored; 'none' when none of them has one.
export function diagState(rows) {
	const s = (rows ?? []).map((r) => r?.diag_status).filter(Boolean);
	if (!s.length) return 'none';
	return worst(s) ?? 'done';
}

const first = (rows, field) => (rows ?? []).map((r) => r?.[field]).find(Boolean) ?? null;

// The id of a related item that may arrive as an expanded object ({ sample_id, sample_code }) or a
// bare id, or be null/absent when the caller cannot read it.
const relId = (v, pk) => (v && typeof v === 'object' ? (v[pk] ?? null) : (v ?? null));
const relCode = (v) => (v && typeof v === 'object' ? (v.sample_code ?? null) : null);

export function buildOverview({ samples = [], operations = [], tests = [], analyses = [] }) {
	const byOp = new Map();
	for (const a of analyses) {
		const k = relId(a.operation_id, 'operation_id');
		if (!k) continue;
		if (!byOp.has(k)) byOp.set(k, []);
		byOp.get(k).push(a);
	}

	const opRows = operations.map((o) => {
		const rows = byOp.get(o.operation_id) ?? [];
		return {
			operation_id: o.operation_id,
			pass_code: o.pass_code ?? null,
			process_category: o.process_category ?? null,
			sample_id: relId(o.sample_id, 'sample_id'),
			sample_code: relCode(o.sample_id),
			analysis: analysisState(rows),
			analysis_error: first(rows.filter((r) => r.status === 'error'), 'error_message'),
			diag: diagState(rows),
			diag_error: first(rows.filter((r) => r.diag_status === 'error'), 'diag_error'),
		};
	});

	// Samples: the junction rows, plus any sample that only appears through an operation or test of
	// this campaign (flagged `member: false` so it can be added to the list).
	const sampleMap = new Map();
	const touch = (id, code, member) => {
		if (!id) return null;
		let s = sampleMap.get(id);
		if (!s) {
			s = { sample_id: id, sample_code: code ?? null, member: false, operations: 0, tests: 0 };
			sampleMap.set(id, s);
		}
		if (code && !s.sample_code) s.sample_code = code;
		if (member) s.member = true;
		return s;
	};
	for (const j of samples) touch(relId(j.sample_id, 'sample_id'), relCode(j.sample_id), true);
	for (const o of opRows) {
		const s = touch(o.sample_id, o.sample_code, false);
		if (s) s.operations++;
	}
	const testRows = tests.map((t) => ({
		session_id: t.session_id,
		test_type: t.test_type ?? null,
		status: t.status ?? null,
		session_date: t.session_date ?? null,
		sample_id: relId(t.sample_id, 'sample_id'),
		sample_code: relCode(t.sample_id),
	}));
	for (const t of testRows) {
		const s = touch(t.sample_id, t.sample_code, false);
		if (s) s.tests++;
	}
	const sampleRows = [...sampleMap.values()].sort((a, b) =>
		String(a.sample_code ?? '').localeCompare(String(b.sample_code ?? ''), undefined, { numeric: true }),
	);

	// Force analysis only applies to machining operations (and anything that already has a row), so
	// the progress denominator is those, not every operation of an imaging campaign.
	const forceOps = opRows.filter((o) => o.process_category === 'machining' || o.analysis !== 'none');
	const countBy = (rows, key) => {
		const out = {};
		for (const r of rows) {
			const k = r[key] ?? 'unknown';
			out[k] = (out[k] ?? 0) + 1;
		}
		return out;
	};
	const analysed = forceOps.filter((o) => o.analysis === 'done').length;
	const diagBuilt = forceOps.filter((o) => o.diag === 'done').length;
	const testsComplete = testRows.filter((t) => t.status === 'complete').length;
	const pct = (n, d) => (d ? Math.round((100 * n) / d) : 0);

	return {
		counts: {
			samples: sampleRows.length,
			operations: opRows.length,
			tests: testRows.length,
			testsByStatus: countBy(testRows, 'status'),
			analysisByState: countBy(forceOps, 'analysis'),
			diagByState: countBy(forceOps, 'diag'),
		},
		progress: {
			forceOps: forceOps.length,
			analysed,
			analysedPct: pct(analysed, forceOps.length),
			diagBuilt,
			diagBuiltPct: pct(diagBuilt, forceOps.length),
			testsComplete,
			testsCompletePct: pct(testsComplete, testRows.length),
		},
		sampleRows,
		opRows,
		testRows,
	};
}

// Text for a visible error from an Axios/Directus failure.
export function errMsg(e) {
	return e?.response?.data?.errors?.[0]?.message || e?.message || 'request failed';
}
