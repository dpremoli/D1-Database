import { test, expect, _electron as electron, type ElectronApplication, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

// Covers the replay-playback transport end to end in the real bundle — the checks that previously
// could only be done by hand: Play advances the playhead at true realtime, Pause freezes it,
// scrubbing moves it both ways, the cut's data reaches the live viewers, and playback stays a
// VIEWER (no safety alarm, no save dialog, nothing written to disk).
//
// The cut itself is synthesised here as real D1LC bytes and served through a stubbed Directus, so
// the test needs no server and no seeded database. Everything downstream of that is real: the
// renderer parses it with the same parseCache the app uses, the playback engine drives the same
// RecordClient buffers a live recording drives, and the FFT panel's spectra come from the real
// sidecar's POST /dsp/spectrum.
//
// Follows save-flow.spec.ts for launching and for the fake-auth/Directus-stub pattern, including
// its cleanup caveat: dev-mode Electron shares the app's real userData profile, so the seeded
// localStorage auth is removed in the finally block or it bleeds into the next launch.

const MAIN_JS = path.join(__dirname, '..', 'dist', 'main.js');

const CACHE_ID = 'test-cache-file-id';
const OPERATION_ID = 'test-operation-id';
// 20 s at 1 kHz. 1 kHz is deliberate: the engine's envelope bin is round(Fs/200) = 5 samples, so
// this exercises the whole-bin path rather than the degenerate binSize == 1 case. The 1 s FFT
// window is also comfortably over the engine's 256-sample floor, so real /dsp/spectrum calls fire.
const FS = 1000;
const N = 20_000;
const CUT_RPM = 1500;
// Above the alarm controller's auto RPM threshold (cfg.rpm default 1200 x 1.02 = 1224). If the
// mode guard in workspace.ts ever regresses, this cut trips the full-screen SAFETY ALARM overlay
// and the assertion below catches it. Forces stay well under the 400 N force threshold so this
// stays a test of the RPM guard specifically.
const PEAK_FZ = 108;

/** A real D1LC live_cache.bin: 32-byte header (<IIIfffff) then six float32[N] arrays.
 *  Layout must match backend/app/d1lc.py's write_d1lc and liveCache.ts's parseCache. */
function makeD1lcCache(): Buffer {
  const head = Buffer.alloc(32);
  head.writeUInt32LE(0x44314c43, 0); // 'D1LC'
  head.writeUInt32LE(1, 4); // version
  head.writeUInt32LE(N, 8);
  head.writeFloatLE(FS, 12);
  head.writeFloatLE(0.05, 16); // feed mm/rev
  head.writeFloatLE(80, 20); // diam mm
  head.writeFloatLE(0, 24); // cut start sec — spiral origin at t=0
  head.writeFloatLE((N - 1) / FS, 28); // cut end sec

  const t = new Float32Array(N), fx = new Float32Array(N), fy = new Float32Array(N);
  const fz = new Float32Array(N), rpm = new Float32Array(N), revs = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    t[i] = i / FS;
    fx[i] = 30 + 5 * Math.sin(i / 13);
    fy[i] = 45 + 5 * Math.cos(i / 17);
    fz[i] = 100 + 8 * Math.sin((2 * Math.PI * 5 * i) / FS);
    rpm[i] = CUT_RPM;
    revs[i] = (CUT_RPM / 60) * (i / FS);
  }
  return Buffer.concat([head, ...[t, fx, fy, fz, rpm, revs].map((a) => Buffer.from(a.buffer.slice(0)))]);
}

async function launch(): Promise<ElectronApplication> {
  const { ELECTRON_RUN_AS_NODE, ...cleanEnv } = process.env;
  return electron.launch({
    args: [MAIN_JS],
    env: { ...cleanEnv, FORCE_APP_TEST_HOOKS: '1' },
    timeout: 30_000,
  });
}

async function readAppConfig(app: ElectronApplication): Promise<{ directusUrl: string; recorderUrl: string }> {
  const userDataDir = await app.evaluate(({ app: electronApp }) => electronApp.getPath('userData'));
  return JSON.parse(fs.readFileSync(path.join(userDataDir, 'config.json'), 'utf-8'));
}

/** One handler for every Directus call, because Playwright matches routes most-recent-first and a
 *  separate catch-all is easy to get backwards. Serves the synthetic cut for the picker, the raw
 *  D1LC bytes for the asset fetch, and the operation row playback reads its RPM from. */
async function stubDirectusAndBypassLogin(window: Page, directusUrl: string, cache: Buffer): Promise<void> {
  const origin = new URL(directusUrl).origin;
  await window.route(`${origin}/**`, (route) => {
    const url = route.request().url();
    if (url.includes(`/assets/${CACHE_ID}`)) {
      return route.fulfill({ status: 200, contentType: 'application/octet-stream', body: cache });
    }
    if (url.includes('/items/machining_force_analysis')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: [{
            id: 'mfa-1',
            live_cache_file: CACHE_ID,
            created_at: '2026-08-27T00:00:00Z',
            operation_id: {
              operation_id: OPERATION_ID,
              pass_code: 'TEST-REPLAY-CUT',
              sample_id: { sample_code: 'TEST-SAMPLE', nickname: 'test' },
            },
          }],
        }),
      });
    }
    if (url.includes(`/items/manufacturing_operations/${OPERATION_ID}`)) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: {
            operation_id: OPERATION_ID,
            machining_spindle_speed_rpm: CUT_RPM,
            machining_operation_subtype: 'MT-R',
            outcome_notes: 'synthetic cut for the playback transport test',
            recorded_metadata: { sample_name: 'TEST-REPLAY-CUT' },
          },
        }),
      });
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data: [] }) });
  });

  await window.evaluate(() => {
    localStorage.setItem('force-app.auth', JSON.stringify({
      accessToken: 'test-access-token',
      refreshToken: 'test-refresh-token',
      expiresAt: Date.now() + 3_600_000,
      user: { id: 'test-user', role: null },
    }));
    // Unlike save-flow.spec.ts this DOES pin the source: the whole point is the replay path, and
    // this machine's persisted default is 'nidaq'.
    localStorage.setItem('force-app.source', 'replay');
  });
  await window.goto('app://force/');
}

/** The scrub input carries the playhead as a precise float; the "0:24 / 1:02" readout is only
 *  second-resolution and too coarse for the pacing assertions. */
async function playheadSec(window: Page): Promise<number> {
  return Number(await window.locator('.transport .scrub').inputValue());
}

function listCaptures(root: string): string[] {
  try {
    return fs.readdirSync(root).filter((n) => /^\d{8}-\d{6}-/.test(n));
  } catch {
    return [];
  }
}

test('replay plays as a video: play/pause/scrub drives the live viewers and writes nothing', async () => {
  const app = await launch();
  const pageErrors: string[] = [];
  try {
    const window = await app.firstWindow();
    window.on('pageerror', (err) => pageErrors.push(err.message));

    await window.waitForURL((url) => url.href.startsWith('app://force/'), { timeout: 30_000 });
    const cfg = await readAppConfig(app);
    const capturesRoot: string = await fetch(`${cfg.recorderUrl}/storage/config`).then((r) => r.json()).then((j) => j.captures_root);
    const capturesBefore = listCaptures(capturesRoot);

    await stubDirectusAndBypassLogin(window, cfg.directusUrl, makeD1lcCache());
    await window.waitForURL((url) => url.href.includes('/record'), { timeout: 15_000 });

    // ---- The transport replaces Start/Stop entirely in replay mode ----
    await expect(window.locator('.transport')).toBeVisible({ timeout: 15_000 });
    await expect(window.locator('.btn.start')).toHaveCount(0);
    await expect(window.locator('.btn.stop')).toHaveCount(0);

    // ---- Pick the cut; the playhead loads it and reports its real duration ----
    const cut = window.locator('.cutlist .cut', { hasText: 'TEST-REPLAY-CUT' });
    await expect(cut).toBeVisible({ timeout: 15_000 });
    await cut.click();

    const scrub = window.locator('.transport .scrub');
    await expect(scrub).toBeEnabled({ timeout: 10_000 });
    const duration = Number(await scrub.getAttribute('max'));
    expect(duration).toBeGreaterThan(19);   // 20 s cut, minus the final sample
    expect(duration).toBeLessThan(21);
    expect(await playheadSec(window)).toBe(0);
    // Shown as m:ss, floored: the last sample sits at (N-1)/FS = 19.999 s, so this reads "0:19".
    await expect(window.locator('.transport .time')).toContainText('/ 0:19');

    // ---- Play: at the 1x default, wall time and cut time advance together ----
    // This is the original complaint stated as an assertion. The old path replayed a long cut
    // several times too fast (min(dt, 0.1) sleep cap) and defaulted to 20x on top of that.
    const play = window.locator('.transport .play');
    await play.click();
    const tPlayStart = Date.now();
    await window.waitForTimeout(2000);
    const advanced = await playheadSec(window);
    const wallSec = (Date.now() - tPlayStart) / 1000;
    console.log(`[timing] playhead advanced ${advanced.toFixed(2)}s of cut in ${wallSec.toFixed(2)}s wall (speed 1x)`);
    // Generous bounds: this asserts "realtime, not a 3x-20x blur", not frame-accurate pacing.
    expect(advanced).toBeGreaterThan(0.7);
    expect(advanced).toBeLessThan(wallSec * 2);

    // ---- The cut's data actually reaches the viewers ----
    // The RPM readout is the cheapest end-to-end proof: it can only show 1500 if the cache was
    // parsed, the playhead advanced over it, and the panel re-rendered off the shared buffers.
    // It also pins the decimation-stride regression, which reported RPM a whole multiple too high.
    await expect(window.locator('.rpm-panel .big')).toHaveText(String(CUT_RPM), { timeout: 10_000 });
    // Target comes from the operation row, not the recording form.
    await expect(window.locator('.rpm-panel .target-lbl')).toContainText(String(CUT_RPM));
    await expect(window.locator('.frm-body canvas')).toBeVisible();

    // ---- Pause freezes the playhead ----
    await play.click();
    const atPause = await playheadSec(window);
    await window.waitForTimeout(1200);
    expect(await playheadSec(window)).toBeCloseTo(atPause, 5);

    // ---- Scrub forwards, then backwards ----
    await scrub.fill('15');
    await expect.poll(() => playheadSec(window)).toBeCloseTo(15, 1);
    await scrub.fill('3');
    await expect.poll(() => playheadSec(window)).toBeCloseTo(3, 1);
    // Still paused after scrubbing — a seek must not start playback.
    await window.waitForTimeout(600);
    expect(await playheadSec(window)).toBeCloseTo(3, 1);
    await expect(window.locator('.rpm-panel .big')).toHaveText(String(CUT_RPM));

    // ---- Playback is a VIEWER: no alarm, no save dialog, nothing on disk ----
    // The cut's 1500 RPM is above the auto alarm threshold (cfg.rpm 1200 x 1.02), so this fails
    // if workspace.ts's record-mode guard on alarms.evaluate regresses.
    await expect(window.locator('.alarm-overlay')).toHaveCount(0);
    await expect(window.locator('.scd-modal')).toHaveCount(0);
    expect(listCaptures(capturesRoot)).toEqual(capturesBefore);
    const status = await fetch(`${cfg.recorderUrl}/record/status`).then((r) => r.json());
    expect(status.state).not.toBe('recording');

    expect(pageErrors).toEqual([]);
  } finally {
    try {
      const window = await app.firstWindow();
      await window.evaluate(() => {
        localStorage.removeItem('force-app.auth');
        localStorage.removeItem('force-app.source');
      });
    } catch {
      /* app may already be in a bad state — best-effort cleanup only */
    }
    await app.close();
  }
});
