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
		cb.addEventListener('change', function () { toggle(name, cb.checked); updateColumnLayout(); schedulePaginate(); });
	});
	function toggle(name, on) {
		document.querySelectorAll('[data-block="' + name + '"]').forEach(function (el) {
			if (el.tagName === 'INPUT') return; // the checkbox itself carries data-block too — never hide it
			el.style.display = on ? '' : 'none';
		});
	}
	var pb = document.getElementById('printBtn'); if (pb) pb.addEventListener('click', function () { window.print(); });

	// "Plots ▾" dropdown: open/close on click, close on an outside click.
	var menu = document.querySelector('.fa-menu'), menuBtn = document.getElementById('faMenuBtn');
	if (menu && menuBtn) {
		menuBtn.addEventListener('click', function (e) { e.stopPropagation(); menu.classList.toggle('open'); });
		document.addEventListener('click', function (e) { if (!menu.contains(e.target)) menu.classList.remove('open'); });
	}

	// If every Force (or every FFT) plot in the "Force Analysis" appendix is
	// hidden, let the remaining side fill the row instead of leaving a blank half.
	function updateColumnLayout() {
		var rows = document.getElementById('faRows');
		if (!rows) return;
		var anyForce = Array.prototype.some.call(rows.querySelectorAll('[data-block^="force-"]'), function (el) { return el.style.display !== 'none'; });
		var anyFft = Array.prototype.some.call(rows.querySelectorAll('[data-block^="fft-"]'), function (el) { return el.style.display !== 'none'; });
		rows.classList.toggle('all-force-hidden', !anyForce);
		rows.classList.toggle('all-fft-hidden', !anyFft);
	}
	updateColumnLayout();

	// Real pagination preview: measure actual rendered block heights and insert a
	// visible "page-gap" spacer immediately before whichever block would actually
	// overflow onto the next printed page — so what you see on screen matches what
	// "Save as PDF" produces, instead of a static line that can drift out of sync.
	var paginateTimer = null;
	function schedulePaginate() { if (paginateTimer) clearTimeout(paginateTimer); paginateTimer = setTimeout(paginate, 120); }
	function paginate() {
		var doc = document.querySelector('.doc');
		if (!doc) return;
		Array.prototype.forEach.call(doc.querySelectorAll('.page-gap'), function (el) { el.remove(); });

		var rect = doc.getBoundingClientRect();
		var mmPx = rect.width / 210; // .doc width is fixed at 210mm (A4)
		var cs = getComputedStyle(doc);
		var padTop = parseFloat(cs.paddingTop) || 16 * mmPx;
		var padBottom = parseFloat(cs.paddingBottom) || padTop;
		var pageContentPx = 297 * mmPx - padTop - padBottom;
		if (!(pageContentPx > 0)) return;

		var units = Array.prototype.slice.call(doc.querySelectorAll('.hd, .grid, .fa-row, .frm-fig, .notes, h2, footer.foot, .tl-item'));
		units = units.filter(function (el) {
			var st = getComputedStyle(el);
			if (st.display === 'none') return false;
			for (var p = el.parentElement; p && p !== doc; p = p.parentElement) { if (units.indexOf(p) !== -1) return false; }
			return true;
		});
		if (!units.length) return;

		var used = 0;
		units.forEach(function (el) {
			var h = el.getBoundingClientRect().height;
			var mb = parseFloat(getComputedStyle(el).marginBottom) || 0;
			if (used > 0 && used + h > pageContentPx) {
				var gap = document.createElement('div');
				gap.className = 'page-gap';
				gap.style.height = Math.max(4, pageContentPx - used) + 'px';
				el.parentNode.insertBefore(gap, el);
				used = 0;
			}
			used += h + mb;
		});
	}
	// FAST sintering trace plots: fetch the normalised CSV same-origin, parse, and
	// draw one small multi-line SVG per plot group (temperature / force+power /
	// pressure). Column i+1 of the CSV corresponds to catalog[i].
	function fmtNum(v) { var a = Math.abs(v); if (a === 0) return '0'; if (a >= 1000) return (v / 1000).toFixed(1) + 'k'; if (a >= 100) return v.toFixed(0); if (a >= 10) return v.toFixed(1); if (a >= 1) return v.toFixed(2); return v.toFixed(3); }
	var NS = 'http://www.w3.org/2000/svg';
	function el(tag, attrs) { var e = document.createElementNS(NS, tag); for (var k in attrs) e.setAttribute(k, attrs[k]); return e; }
	function buildPlot(p, time, data, meta, COLORS) {
		var W = 300, H = 148, ML = 36, MR = 6, MT = 8, MB = 15;
		var t0 = time[0], t1 = time[time.length - 1] || 1;
		var lo = Infinity, hi = -Infinity;
		p.keys.forEach(function (k) { var a = data[k]; if (!a) return; for (var i = 0; i < a.length; i++) { var v = a[i]; if (isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; } } });
		if (!isFinite(lo)) { lo = 0; hi = 1; } if (lo === hi) { lo -= 1; hi += 1; }
		var plotW = W - ML - MR, plotH = H - MT - MB;
		var sx = function (x) { return ML + (x - t0) / (t1 - t0) * plotW; };
		var sy = function (v) { return MT + (1 - (v - lo) / (hi - lo)) * plotH; };
		var stride = Math.max(1, Math.floor(time.length / 400));
		var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, preserveAspectRatio: 'none' });
		function ln(a, b, c, d, s) { svg.appendChild(el('line', { x1: a, y1: b, x2: c, y2: d, stroke: s, 'stroke-width': '0.7' })); }
		ln(ML, MT, ML, H - MB, '#94a3b8'); ln(ML, H - MB, W - MR, H - MB, '#94a3b8');
		[hi, (lo + hi) / 2, lo].forEach(function (v) { var tx = el('text', { x: ML - 3, y: sy(v) + 2, 'text-anchor': 'end', 'class': 'fp-tick' }); tx.textContent = fmtNum(v); svg.appendChild(tx); });
		[[t0, ML, 'start'], [t1, W - MR, 'end']].forEach(function (a) { var tx = el('text', { x: a[1], y: H - 3, 'text-anchor': a[2], 'class': 'fp-tick' }); tx.textContent = fmtNum(a[0]) + 's'; svg.appendChild(tx); });
		var ci = 0;
		p.keys.forEach(function (k) {
			var a = data[k]; if (!a) return; var col = COLORS[ci++ % COLORS.length]; var d = '', pen = false;
			for (var i = 0; i < a.length; i += stride) { var v = a[i]; if (!isFinite(v)) { pen = false; continue; } var X = sx(time[i]).toFixed(1), Y = sy(v).toFixed(1); d += (pen ? 'L' : 'M') + X + ',' + Y + ' '; pen = true; }
			svg.appendChild(el('path', { d: d, fill: 'none', stroke: col, 'stroke-width': '1' }));
		});
		var wrap = document.createElement('div'); wrap.className = 'fp-plot';
		var title = document.createElement('div'); title.className = 'fp-title'; title.textContent = p.title; wrap.appendChild(title);
		wrap.appendChild(svg);
		var leg = document.createElement('div'); leg.className = 'fp-legend'; ci = 0;
		p.keys.forEach(function (k) { var m = meta[k]; if (!m) return; var col = COLORS[ci++ % COLORS.length]; var s = document.createElement('span'); var ic = document.createElement('i'); ic.style.background = col; s.appendChild(ic); s.appendChild(document.createTextNode(m.label + (m.unit ? ' ' + m.unit : ''))); leg.appendChild(s); });
		wrap.appendChild(leg);
		return wrap;
	}
	function drawFast() {
		var host = document.querySelector('.fast-plots[data-file]');
		if (!host) return;
		var file = host.getAttribute('data-file');
		var catalog, plots;
		try { catalog = JSON.parse(host.getAttribute('data-catalog') || '[]'); plots = JSON.parse(host.getAttribute('data-plots') || '[]'); } catch (e) { return; }
		var COLORS = ['#dc2626', '#2563eb', '#16a34a', '#d97706', '#7c3aed', '#0891b2'];
		fetch('/assets/' + file, { credentials: 'same-origin' }).then(function (r) { return r.text(); }).then(function (csv) {
			var lines = csv.split('\\n');
			var keyCol = {}; for (var i = 0; i < catalog.length; i++) keyCol[catalog[i].key] = i + 1;
			var need = {}; plots.forEach(function (p) { p.keys.forEach(function (k) { if (keyCol[k] != null) need[k] = keyCol[k]; }); });
			var time = [], data = {}; Object.keys(need).forEach(function (k) { data[k] = []; });
			for (var r2 = 1; r2 < lines.length; r2++) { if (!lines[r2]) continue; var cells = lines[r2].split(','); time.push(+cells[0]); Object.keys(need).forEach(function (k) { var v = cells[need[k]]; data[k].push(v === '' || v === undefined ? NaN : +v); }); }
			host.innerHTML = '';
			var meta = {}; catalog.forEach(function (c) { meta[c.key] = c; });
			plots.forEach(function (p) { host.appendChild(buildPlot(p, time, data, meta, COLORS)); });
			schedulePaginate();
		}).catch(function () { host.innerHTML = '<div class="fp-msg">Trace unavailable.</div>'; });
	}

	if (document.readyState === 'complete') { schedulePaginate(); drawFast(); }
	else window.addEventListener('load', function () { schedulePaginate(); drawFast(); });
	window.addEventListener('resize', schedulePaginate);
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
						.first('owner_person_id', 'nickname', 'location', 'surface_finish',
							'form', 'diameter_mm', 'length_mm', 'width_mm', 'thickness_mm',
							'gauge_length_mm', 'gauge_width_mm')) || {};

				// Ensure the geometry drawing has every dimension (the flat view omits some).
				for (const k of ['form', 'diameter_mm', 'length_mm', 'width_mm', 'thickness_mm', 'gauge_length_mm', 'gauge_width_mm']) {
					if (ps[k] !== null && ps[k] !== undefined) sample[k] = ps[k];
				}

				const owner = ps.owner_person_id
					? await database('people')
							.where('person_id', ps.owner_person_id)
							.first('full_name', 'email')
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

				// Force/FFT/FRM appendix, only present for processed machining ops
				// (scripts/force_orchestrator.py populates this table).
				const fa = await database('machining_force_analysis')
					.where('operation_id', op.operation_id)
					.andWhere('status', 'done')
					.first('series', 'fft', 'frm_fx', 'frm_fy', 'frm_fz', 'cut_start_idx', 'cut_end_idx', 'sample_rate', 'status', 'trigger_time');

				// FAST sintering ops get a trace-plot appendix instead of the force one.
				const fastRun = op.process_category === 'sintering'
					? await database('fast_run_data')
						.where('operation_id', op.operation_id)
						.andWhere('status', 'done')
						.first('series', 'directus_files_id', 'status')
					: null;

				const publicUrl = String(env.PUBLIC_URL || '').replace(/\/+$/, '');
				const recordUrl = `${publicUrl}/admin/content/manufacturing_operations/${id}`;
				const qrSvg = await QRCode.toString(recordUrl, { type: 'svg', margin: 0, errorCorrectionLevel: 'M' });

				res.set('Content-Security-Policy', REPORT_CSP);
				res.set('Content-Type', 'text/html; charset=utf-8').send(
					renderOperationReport({ op, fa, fastRun, qrSvg, recordUrl, publicUrl })
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
