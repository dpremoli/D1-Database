// Directus endpoint: d1-report (mounted at /d1-report)
//
// GET /d1-report/sample/:id  -> a print-ready (A4, ≤2 page) HTML "Sample Overview"
// document assembling the sample's details, genealogy (parents AND children),
// manufacturing operations and tests, with a locally-generated QR code linking to
// the record. Everything renders server-side and offline — no external services.
//
// :id may be the sample UUID or the human sample_code. Requires a logged-in user.
import { defineEndpoint } from '@directus/extensions-sdk';
import QRCode from 'qrcode';
import { renderSampleReport, renderOperationReport, renderTestReport } from './render.js';

// Report pages are our own self-contained HTML. Directus's global CSP blocks inline
// scripts/handlers, so we (a) serve the toggle/print JS as a same-origin file and
// reference it (allowed by script-src 'self') and (b) set a scoped CSP on report
// responses that permits same-origin scripts and inline styles.
const REPORT_CSP =
	"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self' data:";

const REPORT_JS = `(function () {
	var params = new URLSearchParams(location.search);
	document.querySelectorAll('.toolbar input[data-block]').forEach(function (cb) {
		var name = cb.getAttribute('data-block');
		if (params.get(name) === '0' || params.get(name) === 'false') cb.checked = false;
		toggle(name, cb.checked);
		cb.addEventListener('change', function () { toggle(name, cb.checked); });
	});
	function toggle(name, on) { var el = document.getElementById('block-' + name); if (el) el.style.display = on ? '' : 'none'; }
	var pb = document.getElementById('printBtn'); if (pb) pb.addEventListener('click', function () { window.print(); });
})();`;

export default defineEndpoint({
	id: 'd1-report',
	handler: (router, { database, env, logger }) => {
		// Same-origin toggle/print script (keeps us within Directus's script-src 'self').
		router.get('/report.js', (_req, res) => {
			res.set('Content-Type', 'application/javascript; charset=utf-8').send(REPORT_JS);
		});

		router.get('/sample/:id', async (req, res) => {
			if (!req.accountability?.user) {
				return res.status(401).send('Authentication required.');
			}

			const id = String(req.params.id);
			const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);

			try {
				const sample = await database('v_complete_sample_history')
					.where(isUuid ? { sample_id: id } : { sample_code: id })
					.first();
				if (!sample) return res.status(404).send('Sample not found.');
				const sid = sample.sample_id;

				// physical_samples carries a few fields the flat view omits.
				const ps =
					(await database('physical_samples')
						.where('sample_id', sid)
						.first('owner', 'nickname', 'location', 'surface_finish')) || {};

				const owner = ps.owner
					? await database('directus_users')
							.where('id', ps.owner)
							.first('first_name', 'last_name', 'email')
					: null;

				const [ops, parents, children, tests, opCamps, testCamps] = await Promise.all([
					database('v_manufacturing_operations_full')
						.where('sample_id', sid)
						.orderBy(['operation_date', 'operation_sequence']),
					database('v_sample_genealogy_flat').where('child_sample_id', sid),
					// Children joined to physical_samples for their creation date (timeline).
					database('v_sample_genealogy_flat as g')
						.join('physical_samples as ps', 'g.child_sample_id', 'ps.sample_id')
						.where('g.parent_sample_id', sid)
						.orderBy('ps.created_at')
						.select('g.child_sample_code', 'g.relationship_type', 'g.fraction', 'ps.created_at as child_created', 'ps.form as child_form'),
					database('v_test_sessions_full').where('sample_id', sid).orderBy('session_date'),
					// campaign per operation / test (the views expose project, not campaign)
					database('manufacturing_operations as mo')
						.leftJoin('campaigns as c', 'mo.campaign_id', 'c.campaign_id')
						.where('mo.sample_id', sid)
						.select('mo.operation_id', 'c.campaign_code', 'c.name as campaign_name'),
					database('test_sessions as t')
						.leftJoin('campaigns as c', 't.campaign_id', 'c.campaign_id')
						.where('t.sample_id', sid)
						.select('t.session_id', 'c.campaign_code', 'c.name as campaign_name'),
				]);

				// Attach campaign to each op/test row (project is already on the views).
				const opCamp = Object.fromEntries(opCamps.map((r) => [r.operation_id, r]));
				ops.forEach((o) => {
					const c = opCamp[o.operation_id];
					o.campaign_code = c?.campaign_code;
					o.campaign_name = c?.campaign_name;
				});
				const testCamp = Object.fromEntries(testCamps.map((r) => [r.session_id, r]));
				tests.forEach((t) => {
					const c = testCamp[t.session_id];
					t.campaign_code = c?.campaign_code;
					t.campaign_name = c?.campaign_name;
				});

				const publicUrl = String(env.PUBLIC_URL || '').replace(/\/+$/, '');
				const recordUrl = `${publicUrl}/admin/content/physical_samples/${sid}`;
				const qrSvg = await QRCode.toString(recordUrl, {
					type: 'svg',
					margin: 0,
					errorCorrectionLevel: 'M',
				});

				const html = renderSampleReport({
					sample,
					owner,
					nickname: ps.nickname,
					location: ps.location,
					surfaceFinish: ps.surface_finish,
					ops,
					parents,
					children,
					tests,
					qrSvg,
					recordUrl,
				});
				res.set('Content-Security-Policy', REPORT_CSP);
				res.set('Content-Type', 'text/html; charset=utf-8').send(html);
			} catch (err) {
				logger.error(`d1-report failed for ${id}: ${err.stack || err.message}`);
				res.status(500).send('Report generation failed.');
			}
		});

		// GET /d1-report/operation/:id -> a one-page operation datasheet.
		router.get('/operation/:id', async (req, res) => {
			if (!req.accountability?.user) {
				return res.status(401).send('Authentication required.');
			}
			const id = String(req.params.id);
			try {
				// Query the BASE table (LEFT JOINs) so every operation works — the
				// v_* view only covers machining ops with samples, so FAST/sintering
				// (and other) ops were "not found". mo.* carries all process params.
				const op = await database('manufacturing_operations as mo')
					.leftJoin('physical_samples as ps', 'mo.sample_id', 'ps.sample_id')
					.leftJoin('manufacturing_methods as mm', 'mo.method_id', 'mm.method_id')
					.leftJoin('projects as pr', 'mo.project_id', 'pr.project_id')
					.leftJoin('campaigns as c', 'mo.campaign_id', 'c.campaign_id')
					.leftJoin('equipment as e', 'mo.equipment_id', 'e.equipment_id')
					.where('mo.operation_id', id)
					.first(
						'mo.*',
						'ps.sample_code',
						'mm.method_name',
						'mm.method_code',
						'pr.project_code',
						'pr.project_name',
						'c.campaign_code',
						'c.name as campaign_name',
						'e.equipment_code',
						'e.equipment_name'
					);
				if (!op) return res.status(404).send('Operation not found.');

				const publicUrl = String(env.PUBLIC_URL || '').replace(/\/+$/, '');
				const recordUrl = `${publicUrl}/admin/content/manufacturing_operations/${id}`;
				const qrSvg = await QRCode.toString(recordUrl, { type: 'svg', margin: 0, errorCorrectionLevel: 'M' });

				res.set('Content-Security-Policy', REPORT_CSP);
				res.set('Content-Type', 'text/html; charset=utf-8').send(
					renderOperationReport({ op, qrSvg, recordUrl, publicUrl })
				);
			} catch (err) {
				logger.error(`d1-report operation failed for ${id}: ${err.stack || err.message}`);
				res.status(500).send('Report generation failed.');
			}
		});

		// GET /d1-report/test/:id -> a one-page test datasheet (type-specific params).
		router.get('/test/:id', async (req, res) => {
			if (!req.accountability?.user) return res.status(401).send('Authentication required.');
			const id = String(req.params.id);
			try {
				const t = await database('test_sessions as t')
					.leftJoin('physical_samples as ps', 't.sample_id', 'ps.sample_id')
					.leftJoin('projects as pr', 't.project_id', 'pr.project_id')
					.leftJoin('campaigns as c', 't.campaign_id', 'c.campaign_id')
					.leftJoin('equipment as e', 't.equipment_id', 'e.equipment_id')
					.where('t.session_id', id)
					.first(
						't.*',
						'ps.sample_code',
						'pr.project_code',
						'pr.project_name',
						'c.campaign_code',
						'c.name as campaign_name',
						'e.equipment_code',
						'e.equipment_name'
					);
				if (!t) return res.status(404).send('Test not found.');

				const publicUrl = String(env.PUBLIC_URL || '').replace(/\/+$/, '');
				const recordUrl = `${publicUrl}/admin/content/test_sessions/${id}`;
				const qrSvg = await QRCode.toString(recordUrl, { type: 'svg', margin: 0, errorCorrectionLevel: 'M' });

				res.set('Content-Security-Policy', REPORT_CSP);
				res.set('Content-Type', 'text/html; charset=utf-8').send(
					renderTestReport({ test: t, qrSvg, recordUrl, publicUrl })
				);
			} catch (err) {
				logger.error(`d1-report test failed for ${id}: ${err.stack || err.message}`);
				res.status(500).send('Report generation failed.');
			}
		});
	},
});
