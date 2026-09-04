// Diagnostics Workbench checks for the standalone Force App, in the tests/ui/verify_*.mjs
// convention (env-driven, @playwright/test chromium, generous settle time).
//
// The reason this exists: the analyst reported `diag preview: 401 {"detail":"not permitted"}`
// appearing in the workbench. It was a client-side gap -- directusClient gives axios a
// 401 -> refresh -> retry interceptor, but the diag clients used raw fetch() with
// host.authHeaders(), so once the short-lived access token expired every sidecar request 401'd
// forever. These checks are the regression gate for that, and for the raw-JSON error text
// that made it unreadable.
//
// Run:  FORCE_APP_BASE_URL=http://localhost:5180 FORCE_APP_EMAIL=... FORCE_APP_PASSWORD=... \
//         node tests/ui/verify_diag_workbench.mjs
import { chromium } from '@playwright/test';

const BASE = process.env.FORCE_APP_BASE_URL || 'http://localhost:5180';
const EMAIL = process.env.FORCE_APP_EMAIL || process.env.D1_ADMIN_EMAIL || '';
const PASS = process.env.FORCE_APP_PASSWORD || process.env.D1_ADMIN_PASSWORD || '';

// The shape of the error the analyst saw: "<words>: <status> {". Any visible text matching
// this means a raw sidecar body reached the panel again.
const RAW_ERROR_RE = /\w+\s+\w+:\s*\d{3}\s*[{[]/;

const results = [];
function check(name, pass, detail = '') {
	results.push({ name, pass, detail });
	console.log(`${pass ? 'ok  ' : 'FAIL'}  ${name}${detail ? `  -- ${detail}` : ''}`);
	return pass;
}

(async () => {
	if (!EMAIL || !PASS) {
		console.log('FORCE_APP_EMAIL / FORCE_APP_PASSWORD not set -- this check needs a live backend.');
		process.exit(2);
	}

	const b = await chromium.launch();
	const c = await b.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1700, height: 1050 } });
	const p = await c.newPage();

	// Record every sidecar response and every console error for the whole run.
	const diagResponses = [];
	const consoleErrors = [];
	// The analysis id the workbench is actually working on, read off the request bodies
	// rather than guessed from the DOM.
	let seenAnalysisId = null;
	p.on('request', (r) => {
		if (!r.url().includes('/diag/')) return;
		try {
			const id = JSON.parse(r.postData() || '{}').analysis_id;
			if (id) seenAnalysisId = id;
		} catch { /* not a JSON body */ }
	});
	// Note the distinction: the diag OCTREE files are also served under /diag/, and their
	// range requests are 206s. `api` marks the sidecar endpoints, which are what the auth
	// fix is about; everything under /diag/ still counts for the blanket 401 sweep.
	p.on('response', (r) => {
		const u = r.url();
		if (u.includes('/diag/') || u.includes('/filter/')) {
			diagResponses.push({
				url: u,
				status: r.status(),
				api: /\/(preview|viewport|run|fft|spectrogram)(\?|$)/.test(u),
			});
		}
	});
	p.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });

	// --- log in and reach the workbench ---
	await p.goto(BASE, { waitUntil: 'domcontentloaded' });
	await p.fill('input[type="email"]', EMAIL);
	await p.fill('input[type="password"]', PASS);
	await p.click('button[type="submit"]');
	await p.waitForTimeout(2500);

	await p.goto(`${BASE}/diagnostics`, { waitUntil: 'domcontentloaded' });
	await p.waitForTimeout(6000);

	// The cut picker is a <select>; it self-selects a baked row on load.
	const picker = p.locator('select.diag-picker');
	await picker.waitFor({ state: 'visible', timeout: 30_000 }).catch(() => {});
	await p.waitForTimeout(8000);

	/**
	 * Nudge a recipe parameter. This is the interaction that produced the reported error
	 * storm -- the workbench fires a debounced /diag/preview on every keystroke -- so it is
	 * the one worth driving. Returns false if the panel offers no numeric parameter.
	 */
	async function editRecipeParam() {
		// Steps collapse to a one-line summary; parameters only render once expanded.
		let input = p.locator('.params input[type="number"]').first();
		if (!(await input.count())) {
			const heads = p.locator('.steps .step-head');
			const n = Math.min(await heads.count(), 8);
			for (let i = 0; i < n; i += 1) {
				await heads.nth(i).click().catch(() => {});
				await p.waitForTimeout(250);
				input = p.locator('.params input[type="number"]').first();
				if (await input.count()) break;
			}
		}
		if (!(await input.count())) return false;
		const before = await input.inputValue();
		await input.fill(String((Number(before) || 10) + 1));
		// The parameter inputs bind @change, not @input, so fill() alone is not enough --
		// blur it. The edit also has to make the recipe differ from the bake, or runPreview
		// deliberately returns without requesting anything.
		await input.blur();
		await input.dispatchEvent('change');
		await p.waitForTimeout(6000);
		return true;
	}

	const edited = await editRecipeParam();
	check('a recipe edit reaches the preview endpoint',
		edited && diagResponses.some((r) => r.api),
		edited ? `${diagResponses.filter((r) => r.api).length} api calls` : 'no numeric param rendered');

	check('workbench renders a spatial view',
		(await p.locator('canvas').count()) > 0,
		`${await p.locator('canvas').count()} canvas element(s)`);

	// --- 1. no 401 reached the client at all (the refresh-and-retry works) ---
	// Count the two populations separately. The diag OCTREE is served under /octrees/diag/,
	// so a bare "/diag/" match is dominated by static tile fetches and would make this look
	// well-exercised while never touching the endpoint the fix is about.
	const unauthorized = diagResponses.filter((r) => r.status === 401);
	const apiCalls = diagResponses.filter((r) => r.api);
	check('no request under /diag or /filter ended in 401',
		unauthorized.length === 0,
		unauthorized.length
			? JSON.stringify(unauthorized.slice(0, 3))
			: `${diagResponses.length} total, ${apiCalls.length} of them sidecar API calls`);

	// --- 2. no raw-JSON error text is visible anywhere ---
	const bodyText = await p.locator('body').innerText();
	const rawMatch = bodyText.match(RAW_ERROR_RE);
	check('no raw "<op>: <status> {json}" error text on screen',
		!rawMatch, rawMatch ? rawMatch[0] : '');
	check('the words "not permitted" are not shown to the analyst',
		!/not permitted/i.test(bodyText));

	// --- 3. an expired access token still yields a working preview ---
	// This is the direct test of the fix: drop the access token but keep the refresh token,
	// exactly the state the app reaches after idling, then force a preview.
	const hadRefresh = await p.evaluate(() => {
		for (const k of Object.keys(localStorage)) {
			let v;
			try { v = JSON.parse(localStorage.getItem(k) || 'null'); } catch { continue; }
			if (v && typeof v === 'object' && 'refreshToken' in v && 'accessToken' in v) {
				v.accessToken = null;
				v.expiresAt = 0;
				localStorage.setItem(k, JSON.stringify(v));
				return !!v.refreshToken;
			}
		}
		return false;
	});

	if (hadRefresh) {
		const before = diagResponses.length;
		await p.reload({ waitUntil: 'domcontentloaded' });
		await p.waitForTimeout(4000);
		// If the app bounced to /login, the refresh path failed and that IS the finding --
		// say so rather than reporting a confusing "0 api calls".
		check('an expired access token does not bounce the analyst to /login',
			!/\/login/.test(p.url()), p.url());
		await p.locator('select.diag-picker').waitFor({ state: 'visible', timeout: 30_000 }).catch(() => {});
		await p.waitForTimeout(8000);
		// A bare reload only refetches the baked result; edit a parameter so the sidecar is
		// genuinely exercised with the expired token.
		await editRecipeParam();
		const after = diagResponses.slice(before).filter((r) => r.api);
		const got200 = after.some((r) => r.status === 200);
		const got401 = after.filter((r) => r.status === 401);
		check('a preview succeeds after the access token has expired',
			got200 && got401.length === 0,
			`${after.length} api calls, ${got401.length} unauthorized, statuses ` +
			`${[...new Set(after.map((r) => r.status))].join('/') || 'none'}`);
		const text2 = await p.locator('body').innerText();
		check('no raw error text after the token expiry either',
			!RAW_ERROR_RE.test(text2));
	} else {
		check('found the persisted auth state to expire', false,
			'no localStorage entry with accessToken + refreshToken');
	}

	// --- 4. pop-out mirrors the main window ---
	// Read the analysis id the workbench is showing, open the detached view on it, and check
	// it does not sit on the "no completed bake" message -- i.e. it received state.
	const analysisId = seenAnalysisId;
	if (analysisId) {
		const pop = await c.newPage();
		await pop.goto(`${BASE}/diag-panel/${analysisId}?channel=residZ`, { waitUntil: 'domcontentloaded' });
		await pop.waitForTimeout(8000);
		const popText = await pop.locator('body').innerText();
		check('pop-out advertises that it mirrors the main window',
			/mirrors the main window/i.test(popText), popText.slice(0, 120));
		check('pop-out renders rather than erroring',
			(await pop.locator('canvas').count()) > 0 && !RAW_ERROR_RE.test(popText));
		await pop.screenshot({ path: 'tests/ui/diag_popout.png', fullPage: true });
		await pop.close();
	} else {
		console.log('note: could not read an analysis id from the page; skipped the pop-out check');
	}

	// Console errors are reported but not fatal: Potree/WebGL chatter is expected here.
	const realErrors = consoleErrors.filter((e) => /401|not permitted|diag preview|diag viewport/i.test(e));
	check('no auth-related console errors', realErrors.length === 0, realErrors.slice(0, 3).join(' | '));

	await p.screenshot({ path: 'tests/ui/diag_workbench.png', fullPage: true });
	await b.close();

	const failed = results.filter((r) => !r.pass);
	console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
	console.log(failed.length ? 'FAIL' : 'PASS');
	process.exit(failed.length ? 1 : 0);
})();
