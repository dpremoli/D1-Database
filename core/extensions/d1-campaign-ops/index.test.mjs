// Run with: node --test core/extensions/d1-campaign-ops/index.test.mjs
// Tests the overview roll-up (src/overview.js); the Vue panel itself needs a live Directus.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { TEST_STATUS_ORDER, analysisState, buildOverview, diagState, isDuplicate, isForbidden } from './src/overview.js';

test('analysisState rolls several files up, worst first', () => {
	assert.equal(analysisState([]), 'none');
	assert.equal(analysisState(undefined), 'none');
	assert.equal(analysisState([{ status: 'done' }, { status: 'error' }]), 'error');
	assert.equal(analysisState([{ status: 'done' }, { status: 'processing' }, { status: 'pending' }]), 'processing');
	assert.equal(analysisState([{ status: 'done' }, { status: 'pending' }]), 'pending');
	assert.equal(analysisState([{ status: 'done' }, { status: 'skipped' }]), 'done');
	assert.equal(analysisState([{ status: 'skipped' }]), 'skipped');
});

test('diagState treats a missing diag_status as not built', () => {
	assert.equal(diagState([]), 'none');
	assert.equal(diagState([{ diag_status: null }, {}]), 'none');
	assert.equal(diagState([{ diag_status: 'done' }, { diag_status: 'done' }]), 'done');
	// one built file and one never requested: the operation is not built
	assert.equal(diagState([{ diag_status: 'done' }, { diag_status: null }]), 'none');
	assert.equal(diagState([{ diag_status: 'done' }, { diag_status: 'error' }]), 'error');
	assert.equal(diagState([{ diag_status: 'pending' }, { diag_status: 'done' }]), 'pending');
	assert.equal(diagState([{ diag_status: null }, { diag_status: 'processing' }]), 'processing');
});

test('diagnostics progress does not count an operation with an unbuilt file', () => {
	const o = buildOverview({
		operations: [
			{ operation_id: 'o1', process_category: 'machining' },
			{ operation_id: 'o2', process_category: 'machining' },
		],
		analyses: [
			{ operation_id: 'o1', status: 'done', diag_status: 'done' },
			{ operation_id: 'o1', status: 'done', diag_status: null },
			{ operation_id: 'o2', status: 'done', diag_status: 'done' },
		],
	});
	assert.equal(o.progress.analysed, 2);
	assert.equal(o.progress.diagBuilt, 1);
	assert.equal(o.progress.diagBuiltPct, 50);
});

test('operations whose force files were all skipped are not in the force-analysis denominator', () => {
	const o = buildOverview({
		operations: [
			{ operation_id: 'o1', process_category: 'machining' },
			{ operation_id: 'o2', process_category: 'machining' },
			{ operation_id: 'o3', process_category: 'machining' },
		],
		analyses: [
			{ operation_id: 'o1', status: 'done', diag_status: 'done' },
			{ operation_id: 'o2', status: 'skipped' },
			{ operation_id: 'o2', status: 'skipped' },
			// o3 mixes done and skipped: it is analysed, and stays in
			{ operation_id: 'o3', status: 'done' },
			{ operation_id: 'o3', status: 'skipped' },
		],
	});
	assert.equal(o.progress.forceOps, 2);
	assert.equal(o.progress.analysed, 2);
	assert.equal(o.progress.analysedPct, 100);
	assert.equal(o.progress.diagBuilt, 1);
	// the skipped operation is still listed with its state
	assert.equal(o.opRows.find((r) => r.operation_id === 'o2').analysis, 'skipped');
});

const S1 = { sample_id: 's1', sample_code: '9-A-1' };
const S2 = { sample_id: 's2', sample_code: '9-A-2' };
const S10 = { sample_id: 's10', sample_code: '9-A-10' };

test('buildOverview counts, per-sample rows and progress', () => {
	const o = buildOverview({
		samples: [{ sample_id: S10 }, { sample_id: S1 }],
		operations: [
			{ operation_id: 'o1', pass_code: 'P1', process_category: 'machining', sample_id: S1 },
			{ operation_id: 'o2', pass_code: 'P2', process_category: 'machining', sample_id: S1 },
			{ operation_id: 'o3', pass_code: 'P3', process_category: 'machining', sample_id: S2 },
			{ operation_id: 'o4', pass_code: 'F1', process_category: 'fast', sample_id: S2 },
		],
		tests: [
			{ session_id: 't1', test_type: 'tensile', status: 'processed', sample_id: S1 },
			{ session_id: 't2', test_type: 'tensile', status: 'registered', sample_id: S10 },
		],
		analyses: [
			{ operation_id: 'o1', status: 'done', diag_status: 'done' },
			{ operation_id: 'o2', status: 'error', error_message: 'bad file', diag_status: null },
			// o3 has no analysis row yet
		],
	});
	assert.equal(o.counts.samples, 3); // S1, S10 from the junction + S2 via its operations
	assert.equal(o.counts.operations, 4);
	assert.equal(o.counts.tests, 2);
	assert.deepEqual(o.counts.testsByStatus, { processed: 1, registered: 1 });
	// natural order, member flag, per-sample counts
	assert.deepEqual(
		o.sampleRows.map((s) => [s.sample_code, s.member, s.operations, s.tests]),
		[
			['9-A-1', true, 2, 1],
			['9-A-2', false, 2, 0],
			['9-A-10', true, 0, 1],
		],
	);
	// FAST operation without a force row is not part of the force-analysis denominator
	assert.equal(o.progress.forceOps, 3);
	assert.equal(o.progress.analysed, 1);
	assert.equal(o.progress.analysedPct, 33);
	assert.equal(o.progress.diagBuilt, 1);
	assert.equal(o.progress.testsCompletePct, 50);
	assert.deepEqual(o.counts.analysisByState, { done: 1, error: 1, none: 1 });
	const o2 = o.opRows.find((r) => r.operation_id === 'o2');
	assert.equal(o2.analysis, 'error');
	assert.equal(o2.analysis_error, 'bad file');
	assert.equal(o2.sample_code, '9-A-1');
});

test('an empty campaign gives zeros, not NaN', () => {
	const o = buildOverview({});
	assert.equal(o.counts.samples, 0);
	assert.equal(o.progress.analysedPct, 0);
	assert.equal(o.progress.testsCompletePct, 0);
	assert.deepEqual(o.sampleRows, []);
});

test('rows whose related sample is unreadable (null) do not crash and add no sample', () => {
	const o = buildOverview({
		samples: [{ sample_id: null }],
		operations: [{ operation_id: 'o1', pass_code: 'P1', process_category: 'machining', sample_id: null }],
		tests: [{ session_id: 't1', status: 'processed', sample_id: null }],
	});
	assert.equal(o.counts.samples, 0);
	assert.equal(o.counts.operations, 1);
	assert.equal(o.counts.tests, 1);
});

test('tests complete counts processed and analysed (the migration-0013 vocabulary), not the retired complete', () => {
	const statuses = ['registered', 'pending_processing', 'processing', 'processed', 'analysing', 'analysed', 'failed'];
	const o = buildOverview({ tests: statuses.map((status, i) => ({ session_id: `t${i}`, status })) });
	assert.equal(o.progress.testsComplete, 2);
	assert.equal(o.progress.testsCompletePct, 29);
	// the retired pre-0013 value cannot occur any more, so it must not be counted
	assert.equal(buildOverview({ tests: [{ session_id: 'x', status: 'complete' }] }).progress.testsComplete, 0);
	// every status of the lifecycle has a chip position
	assert.deepEqual([...TEST_STATUS_ORDER].sort(), [...statuses].sort());
});

test('isForbidden is true only for permission failures, not for other errors', () => {
	const http = (status, code) => ({ response: { status, data: { errors: [{ extensions: { code } }] } } });
	assert.equal(isForbidden(http(403, 'FORBIDDEN')), true);
	assert.equal(isForbidden({ response: { status: 403 } }), true);
	assert.equal(isForbidden(http(200, 'FORBIDDEN')), true);
	assert.equal(isForbidden(http(500, 'INTERNAL_SERVER_ERROR')), false);
	assert.equal(isForbidden(http(503)), false);
	assert.equal(isForbidden(new Error('Network Error')), false);
	assert.equal(isForbidden(undefined), false);
});

test('isDuplicate recognises a unique-constraint failure', () => {
	assert.equal(isDuplicate({ response: { status: 400, data: { errors: [{ extensions: { code: 'RECORD_NOT_UNIQUE' } }] } } }), true);
	assert.equal(isDuplicate({ response: { status: 400, data: { errors: [{ extensions: { code: 'INVALID_PAYLOAD' } }] } } }), false);
	assert.equal(isDuplicate(new Error('x')), false);
});
