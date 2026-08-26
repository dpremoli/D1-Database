# Replay Playback Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Recording workspace's "Replay file" source into a video-style player — play, pause, and scrub an archived cut through the live viewers — and fix two reproduced defects in the existing `/record/start_replay` path.

**Architecture:** The playhead runs in the browser over a locally-parsed D1LC cache and fills the same `RecordClient` buffers the WebSocket fills, so every panel works unchanged. Spectra stay in Python: a new stateless `POST /dsp/spectrum` on the recorder sidecar runs the same `scipy.signal.welch` call the live path already uses. Nothing is written to disk during playback.

**Tech Stack:** FastAPI + numpy/scipy (backend), Vue 3 + TypeScript + Vitest (frontend), pytest (backend tests).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-26-replay-playback-transport-design.md`. Read it before Task 1.
- Playback writes nothing to disk, opens no `RecordingSession`, and never opens the Save dialog.
- Playback applies **no** `FilterChain`. Live applies none, so neither does playback.
- Playback must not evaluate the alarm controller — an archived cut cannot trip a safety alarm.
- FRM geometry in playback comes from the cache's `revs` array via the `liveCloud` formula (`theta = 2*PI*r`, `rho = D/2 - Feed*r`, `r = (revs[i] - revs[cs]) / ppr`), never from re-integration.
- Default replay speed is `1` (true realtime). Speed input `min` is `0.1`.
- Backend run: `apps/force-app/backend/.venv/Scripts/python.exe -m pytest` from `apps/force-app/backend`.
- Frontend run: `npm test` from `apps/force-app/web` (vitest 4).
- Branch: `feat/replay-playback-transport`. Commit after every task.

---

### Task 1: Fix live-replay RPM (decimation-stride mismatch)

`RecordingSession` builds `FrmIntegrator` from `cfg`, whose `sample_rate` the replay endpoint sets
to the cache's *original* rate — but `ReplaySource` streams at `fs / stride`. Live RPM comes out
high by `stride`. `CutDetector` and `_update_fft` already use `source.rate`; this makes
`FrmIntegrator` agree.

**Files:**
- Modify: `apps/force-app/backend/app/acquisition/consumers.py:107-118`
- Modify: `apps/force-app/backend/app/session.py:72`
- Test: `apps/force-app/backend/tests/test_replay.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `FrmIntegrator(cfg, fs=None, max_points_per_frame=300)` — `fs` defaults to
  `cfg.sample_rate` when omitted, so the two existing callers in
  `tests/test_drift_cut.py:96` and `tests/test_sim_consumers.py:49` keep working unchanged.

- [ ] **Step 1: Write the failing test**

Append to `apps/force-app/backend/tests/test_replay.py`:

```python
def test_replay_live_rpm_survives_decimation(tmp_path):
    """A cut long enough to force stride > 1 must still report the cache's true RPM live.

    Regression: /record/start_replay sets cfg.sample_rate to the cache's ORIGINAL rate while
    ReplaySource streams at fs/stride, so FrmIntegrator (which read cfg.sample_rate) reported
    RPM high by exactly `stride`. Every fixture above is stride == 1, which is why it was missed.
    """
    n, fs = 400_000, 20_000.0  # 20 s; > the 300k cap, so ReplaySource decimates
    cache, _ = _make_cache(tmp_path, n=n, fs=fs, rpm=1500.0)
    src = ReplaySource(cache, ppr=1, realtime=False)
    assert src.rate < fs, "fixture must actually decimate or it cannot catch this"

    # Exactly what main.py:record_start_replay builds — cfg.sample_rate is the ORIGINAL fs.
    cfg = RecordConfig(
        sample_name="REPLAY-DECIMATED", axis="Fz",
        feed=src.feed, diam=src.diam, sample_rate=fs, duration_sec=n / fs, ppr=1,
    )
    sess = RecordingSession(cfg, str(tmp_path), src, broadcaster=None)
    sess.start()
    sess._thread.join(120)
    sess.join_finalize(120)
    assert sess.state == "done", sess.error
    assert abs(sess.frm._last_rpm - 1500.0) / 1500.0 < 0.05, (
        f"live RPM {sess.frm._last_rpm:.0f} != 1500 (stride {fs / src.rate:.0f}x error)"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/force-app/backend && .venv/Scripts/python.exe -m pytest tests/test_replay.py::test_replay_live_rpm_survives_decimation -v
```
Expected: FAIL — `live RPM 3000 != 1500 (stride 2x error)`.

- [ ] **Step 3: Give FrmIntegrator its own fs**

In `consumers.py`, change the constructor signature and the `self.fs` line only:

```python
    def __init__(self, cfg: RecordConfig, fs: float | None = None, max_points_per_frame: int = 300):
        self.cfg = cfg
        self.max_pts = max_points_per_frame
        # The rate data ACTUALLY arrives at, which is not always cfg.sample_rate: a ReplaySource
        # decimates a long cut and streams at fs/stride, so reading cfg.sample_rate here reported
        # RPM high by exactly that stride. Callers that genuinely acquire at cfg.sample_rate can
        # omit it. CutDetector and session._update_fft already take source.rate for this reason.
        self.fs = float(cfg.sample_rate if fs is None else fs)
```

In `session.py:72`:

```python
        self.frm = FrmIntegrator(cfg, self.source.rate)
```

- [ ] **Step 4: Run the full backend suite**

```bash
cd apps/force-app/backend && .venv/Scripts/python.exe -m pytest tests/ -q
```
Expected: the new test PASSES; `test_drift_cut.py` and `test_sim_consumers.py` still pass via the `fs=None` default.

- [ ] **Step 5: Commit**

```bash
git add apps/force-app/backend/app/acquisition/consumers.py apps/force-app/backend/app/session.py apps/force-app/backend/tests/test_replay.py
git commit -m "fix(force-app): live replay RPM was high by the decimation stride"
```

---

### Task 2: Fix ReplaySource pacing cap

`read()` caps its pacing sleep at `min(dt, 0.1)`. The target is absolute, so an under-sleep is
never repaid and any chunk representing more than 0.1 s of wall time replays too fast — a 120 s
cut takes 40 s at 1x.

**Files:**
- Modify: `apps/force-app/backend/app/sources/replay.py:90-95`
- Test: `apps/force-app/backend/tests/test_replay.py`

**Interfaces:**
- Consumes: nothing.
- Produces: no signature change. `ReplaySource.read()` honours `speed` for cuts of any length.

- [ ] **Step 1: Write the failing test**

Append to `apps/force-app/backend/tests/test_replay.py`:

```python
def test_replay_honours_speed_on_long_chunks(tmp_path):
    """Pacing must track the requested speed even when a chunk exceeds the old 0.1 s sleep cap.

    Chunks are sized so any replay is ~400 of them, so a long cut has long chunks. The old
    min(dt, 0.1) cap under-slept every one of them and never caught up, giving a ~40 s floor
    per replay however long the cut really was.
    """
    import time

    n, fs = 200_000, 2_000.0  # 100 s of cut; chunk lands well above 0.1 s of wall time at 1x
    cache, _ = _make_cache(tmp_path, n=n, fs=fs, rpm=1500.0)
    src = ReplaySource(cache, ppr=1, realtime=True, speed=1.0)
    chunk_sec = src.chunk / src.rate
    assert chunk_sec > 0.1, f"fixture chunk {chunk_sec:.3f}s must exceed the old cap"

    src.start()
    t0 = time.perf_counter()
    reads = 5
    for _ in range(reads):
        assert src.read() is not None
    wall = time.perf_counter() - t0
    played = reads * chunk_sec
    # Allow generous slack for scheduler jitter; the bug was a 3x+ overspeed, not a few percent.
    assert wall > played * 0.7, f"played {played:.2f}s of cut in {wall:.2f}s wall — too fast"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/force-app/backend && .venv/Scripts/python.exe -m pytest tests/test_replay.py::test_replay_honours_speed_on_long_chunks -v
```
Expected: FAIL — wall time is ~0.5 s against ~2.5 s of cut played.

- [ ] **Step 3: Sleep to the actual target**

Replace the tail of `read()` in `replay.py`:

```python
        if self.realtime:
            target = self._t0 + float(t[-1]) / self.speed
            dt = target - time.perf_counter()
            # Sleep the WHOLE remaining interval, in slices, so stop() still interrupts promptly.
            # The old min(dt, 0.1) cap under-slept every chunk longer than 0.1 s and — because the
            # target is absolute — never repaid it, so a 120 s cut replayed in 40 s at 1x.
            while dt > 0:
                if self._stop.wait(min(dt, 0.1)):
                    break
                dt = target - time.perf_counter()
        return t, data
```

- [ ] **Step 4: Run the replay tests**

```bash
cd apps/force-app/backend && .venv/Scripts/python.exe -m pytest tests/test_replay.py -v
```
Expected: all PASS. The `realtime=False` tests are unaffected (they never enter the branch), and
`stop()` still breaks the wait immediately because `_stop` is the same `threading.Event`.

- [ ] **Step 5: Commit**

```bash
git add apps/force-app/backend/app/sources/replay.py apps/force-app/backend/tests/test_replay.py
git commit -m "fix(force-app): replay ignored requested speed on long chunks"
```

---

### Task 3: Extract `welch_spectra` so live and playback cannot drift

`session._update_fft` computes spectra inline. Playback needs the identical computation behind an
endpoint. Extract it to `dsp.py` and have `_update_fft` call it, so there is exactly one
implementation.

**Files:**
- Modify: `apps/force-app/backend/app/dsp.py`
- Modify: `apps/force-app/backend/app/session.py:297-343`
- Test: `apps/force-app/backend/tests/test_dsp.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `welch_spectra(bufs: dict[str, np.ndarray], fs: float, nperseg: int, min_samples: int = 256, max_bins: int = 240) -> tuple[list[float] | None, dict[str, list[float]]]`
  returning `(f, spectra)` where `f` is the decimated frequency axis (2 dp) and `spectra` maps
  channel name to **amplitude** (sqrt of PSD, 4 dp). Returns `(None, {})` when every buffer is
  shorter than `min_samples`. Tasks 4 and 5 depend on this exact shape.

- [ ] **Step 1: Write the failing test**

Append to `apps/force-app/backend/tests/test_dsp.py`:

```python
def test_welch_spectra_peaks_at_the_input_frequency():
    import numpy as np

    from app.dsp import welch_spectra

    fs, n, f0 = 2000.0, 4096, 120.0
    t = np.arange(n) / fs
    bufs = {
        "Fz": np.sin(2 * np.pi * f0 * t),
        "Fx": np.zeros(n),
        "Short": np.zeros(10),  # below min_samples — must be dropped, not crash
    }
    f, spectra = welch_spectra(bufs, fs=fs, nperseg=1024)

    assert f is not None
    assert "Short" not in spectra
    assert set(spectra) == {"Fz", "Fx"}
    assert len(f) == len(spectra["Fz"]) <= 240
    peak_hz = f[int(np.argmax(spectra["Fz"]))]
    assert abs(peak_hz - f0) < 10.0, f"peak at {peak_hz} Hz, expected ~{f0}"


def test_welch_spectra_empty_when_all_buffers_too_short():
    import numpy as np

    from app.dsp import welch_spectra

    f, spectra = welch_spectra({"Fz": np.zeros(4)}, fs=1000.0, nperseg=256)
    assert f is None and spectra == {}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/force-app/backend && .venv/Scripts/python.exe -m pytest tests/test_dsp.py -k welch -v
```
Expected: FAIL — `ImportError: cannot import name 'welch_spectra'`.

- [ ] **Step 3: Add `welch_spectra` to `dsp.py`**

`dsp.py` currently imports only numpy, so add the scipy import first:

```python
from scipy import signal as ssig
```

Then append:

```python
def welch_spectra(
    bufs: dict[str, np.ndarray],
    fs: float,
    nperseg: int,
    min_samples: int = 256,
    max_bins: int = 240,
) -> tuple[list[float] | None, dict[str, list[float]]]:
    """Welch AMPLITUDE spectra for a set of named channel buffers, decimated for the wire.

    One implementation shared by the live recording path (session._update_fft) and the
    /dsp/spectrum endpoint that playback calls, so a replayed cut's FFT cannot drift from a
    live one's. Buffers shorter than `min_samples` are skipped rather than erroring, since
    live chunks arrive before the rolling window has filled.

    Returns (f, {name: amp}) with f decimated to at most `max_bins` points, or (None, {}) if
    no buffer was long enough.
    """
    f: np.ndarray | None = None
    psd: dict[str, np.ndarray] = {}
    for name, buf in bufs.items():
        if buf.size < min_samples:
            continue
        f, p = ssig.welch(buf, fs=fs, nperseg=min(int(nperseg), buf.size))
        psd[name] = p
    if f is None:
        return None, {}
    step = max(1, f.size // max_bins)
    fout = f[::step].round(2).tolist()
    return fout, {n: np.sqrt(p[::step]).round(4).tolist() for n, p in psd.items()}
```

- [ ] **Step 4: Rewrite `_update_fft` to call it**

In `session.py`, replace everything from `now = time.perf_counter()` to the end of `_update_fft`:

```python
        now = time.perf_counter()
        if now - self._fft_last < 0.3 or self._fft_bufs[self._fft_axis].size < 256:
            return
        self._fft_last = now
        fs = float(self.source.rate)
        nper = int(min(self._fft_bufs[self._fft_axis].size, 4096))
        fout, spectra_out = welch_spectra(self._fft_bufs, fs=fs, nperseg=nper)
        if fout is None:
            return
        self._publish_control(
            {
                "type": "fft",
                "fs": fs,
                "f": fout,
                "spectra": spectra_out,
                "axis": self._fft_axis,  # back-compat
                "amp": spectra_out.get(self._fft_axis, []),  # back-compat
            }
        )
```

Update the import at `session.py:22` to `from .dsp import sum_axes, tacho_column, welch_spectra`,
and drop the now-unused `from scipy import signal as ssig` at line 14.

- [ ] **Step 5: Run the full backend suite**

```bash
cd apps/force-app/backend && .venv/Scripts/python.exe -m pytest tests/ -q
```
Expected: all PASS. This is a pure refactor — `test_pipeline.py` and `test_api.py` exercise the
live FFT path and must be unchanged.

- [ ] **Step 6: Commit**

```bash
git add apps/force-app/backend/app/dsp.py apps/force-app/backend/app/session.py apps/force-app/backend/tests/test_dsp.py
git commit -m "refactor(force-app): extract welch_spectra shared by live and playback"
```

---

### Task 4: `POST /dsp/spectrum` endpoint

Stateless. Binary body rather than JSON: 12 channels x ~5000 float32 is ~240 KB raw against
roughly 3 MB as JSON text, and this runs a few times a second.

**Files:**
- Modify: `apps/force-app/backend/app/main.py` (add after `record_start_replay`, before `/record/stop`)
- Test: `apps/force-app/backend/tests/test_spectrum_api.py` (create)

**Interfaces:**
- Consumes: `welch_spectra` from Task 3.
- Produces: `POST /dsp/spectrum?fs=<float>&names=<csv>&nperseg=<int>` with an
  `application/octet-stream` body of little-endian float32, channel-major, length
  `len(names) * n_samples`. Responds
  `{"fs": float, "f": [float], "spectra": {name: [float]}}` — the same `f`/`spectra` shape the
  live WS `fft` control message carries. Task 5 consumes this.

- [ ] **Step 1: Write the failing test**

Create `apps/force-app/backend/tests/test_spectrum_api.py`:

```python
"""POST /dsp/spectrum — the stateless Welch endpoint playback uses for its FFT panel."""

import numpy as np
from fastapi.testclient import TestClient

from app.dsp import welch_spectra
from app.main import app

client = TestClient(app)


def _body(*channels: np.ndarray) -> bytes:
    return np.concatenate(channels).astype("<f4").tobytes()


def test_spectrum_peaks_at_the_input_frequency():
    fs, n, f0 = 2000.0, 4096, 120.0
    t = np.arange(n) / fs
    fz = np.sin(2 * np.pi * f0 * t)
    res = client.post(
        "/dsp/spectrum",
        params={"fs": fs, "names": "Fz", "nperseg": 1024},
        content=_body(fz),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["fs"] == fs
    peak_hz = body["f"][int(np.argmax(body["spectra"]["Fz"]))]
    assert abs(peak_hz - f0) < 10.0


def test_spectrum_matches_welch_spectra_exactly():
    """The endpoint and the live path must not drift — same input, same numbers."""
    fs, n = 2000.0, 4096
    rng = np.random.default_rng(0)
    fx = rng.standard_normal(n).astype("<f4")
    fz = rng.standard_normal(n).astype("<f4")
    res = client.post(
        "/dsp/spectrum",
        params={"fs": fs, "names": "Fx,Fz", "nperseg": 1024},
        content=_body(fx, fz),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    f_ref, spec_ref = welch_spectra(
        {"Fx": fx.astype(np.float64), "Fz": fz.astype(np.float64)}, fs=fs, nperseg=1024
    )
    assert body["f"] == f_ref
    assert body["spectra"] == spec_ref


def test_spectrum_rejects_a_body_that_is_not_a_multiple_of_the_channel_count():
    res = client.post(
        "/dsp/spectrum",
        params={"fs": 1000.0, "names": "Fx,Fz"},
        content=np.zeros(101, dtype="<f4").tobytes(),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert res.status_code == 422


def test_spectrum_reports_no_bins_when_the_window_is_too_short():
    res = client.post(
        "/dsp/spectrum",
        params={"fs": 1000.0, "names": "Fz"},
        content=np.zeros(8, dtype="<f4").tobytes(),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert res.status_code == 200
    assert res.json() == {"fs": 1000.0, "f": [], "spectra": {}}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/force-app/backend && .venv/Scripts/python.exe -m pytest tests/test_spectrum_api.py -v
```
Expected: FAIL with 404 — the route does not exist.

- [ ] **Step 3: Add the endpoint**

`main.py` imports neither numpy nor anything from `.dsp` today, so add both alongside the
existing `from .d1lc import read_d1lc_header` line:

```python
import numpy as np

from .dsp import welch_spectra
```

(`Request`, `HTTPException` and `run_in_threadpool` are already imported.) Then insert before
`@app.post("/record/stop")`:

```python
@app.post("/dsp/spectrum")
async def dsp_spectrum(request: Request, fs: float, names: str, nperseg: int = 4096) -> dict:
    """Welch amplitude spectra for one window of samples. Stateless — no session, no playhead.

    Playback (an archived cut scrubbed in the browser) calls this a few times a second so its
    FFT panel is computed by the SAME scipy path as a live recording's, rather than by a second
    implementation in the frontend that could drift. Body is little-endian float32,
    channel-major, len(names) * n_samples.
    """
    chan_names = [n for n in names.split(",") if n]
    if not chan_names:
        raise HTTPException(422, "names must list at least one channel")
    raw = await request.body()
    flat = np.frombuffer(raw, dtype="<f4")
    if flat.size % len(chan_names):
        raise HTTPException(
            422, f"body has {flat.size} samples, not a multiple of {len(chan_names)} channels"
        )
    n = flat.size // len(chan_names)
    bufs = {
        name: flat[i * n : (i + 1) * n].astype(np.float64)
        for i, name in enumerate(chan_names)
    }
    # Welch is CPU-bound; keep it off the event loop so concurrent requests aren't stalled.
    f, spectra = await run_in_threadpool(
        welch_spectra, bufs, fs=fs, nperseg=max(1, int(nperseg))
    )
    return {"fs": fs, "f": f or [], "spectra": spectra}
```

- [ ] **Step 4: Run the tests**

```bash
cd apps/force-app/backend && .venv/Scripts/python.exe -m pytest tests/test_spectrum_api.py tests/test_api.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/force-app/backend/app/main.py apps/force-app/backend/tests/test_spectrum_api.py
git commit -m "feat(force-app): stateless POST /dsp/spectrum for playback FFT"
```

---

### Task 5: Frontend spectrum client (throttle + coalesce)

**Files:**
- Create: `apps/force-app/web/src/record/playback/spectrum.ts`
- Test: `apps/force-app/web/src/record/playback/spectrum.test.ts`

**Interfaces:**
- Consumes: `POST /dsp/spectrum` from Task 4.
- Produces:
  - `interface SpectrumReply { fs: number; f: number[]; spectra: Record<string, number[]> }`
  - `createSpectrumClient(baseUrl: string, opts?: { minIntervalMs?: number }): SpectrumClient`
  - `interface SpectrumClient { request(req: SpectrumRequest): void; onReply: (r: SpectrumReply) => void; onError: (e: Error) => void; flush(): Promise<void>; dispose(): void }`
  - `interface SpectrumRequest { fs: number; names: string[]; samples: Float32Array; nperseg?: number; force?: boolean }`
  - `request()` is fire-and-forget. It throttles to `minIntervalMs` (default 300, matching
    `_update_fft`), and while a call is in flight it keeps only the newest pending request.
    `force: true` bypasses the throttle (used on scrub release). Task 6 consumes this.

- [ ] **Step 1: Write the failing test**

Create `apps/force-app/web/src/record/playback/spectrum.test.ts`:

```ts
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { createSpectrumClient } from './spectrum';

const REPLY = { fs: 1000, f: [0, 10, 20], spectra: { Fz: [1, 2, 3] } };

function okFetch() {
	return vi.fn(async () => ({ ok: true, status: 200, json: async () => REPLY }) as any);
}

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

const req = (n = 4) => ({ fs: 1000, names: ['Fz'], samples: new Float32Array(n) });

describe('spectrum client', () => {
	it('sends the window as float32 to /dsp/spectrum with names and fs in the query', async () => {
		const f = okFetch();
		vi.stubGlobal('fetch', f);
		const c = createSpectrumClient('http://localhost:8200');
		const replies: any[] = [];
		c.onReply = (r) => replies.push(r);
		c.request({ fs: 1000, names: ['Fx', 'Fz'], samples: new Float32Array([1, 2, 3, 4]) });
		await c.flush();

		expect(f).toHaveBeenCalledTimes(1);
		const [url, init] = f.mock.calls[0];
		expect(String(url)).toContain('/dsp/spectrum');
		expect(String(url)).toContain('fs=1000');
		expect(String(url)).toContain('names=Fx%2CFz');
		expect(init.method).toBe('POST');
		expect(new Float32Array(init.body)).toEqual(new Float32Array([1, 2, 3, 4]));
		expect(replies).toEqual([REPLY]);
	});

	it('throttles to minIntervalMs', async () => {
		const f = okFetch();
		vi.stubGlobal('fetch', f);
		const c = createSpectrumClient('http://x', { minIntervalMs: 300 });
		c.request(req());
		await c.flush();
		expect(f).toHaveBeenCalledTimes(1);

		c.request(req());          // immediately after — inside the throttle window
		await c.flush();
		expect(f).toHaveBeenCalledTimes(1);

		vi.advanceTimersByTime(301);
		c.request(req());
		await c.flush();
		expect(f).toHaveBeenCalledTimes(2);
	});

	it('force bypasses the throttle', async () => {
		const f = okFetch();
		vi.stubGlobal('fetch', f);
		const c = createSpectrumClient('http://x', { minIntervalMs: 300 });
		c.request(req());
		await c.flush();
		c.request({ ...req(), force: true });
		await c.flush();
		expect(f).toHaveBeenCalledTimes(2);
	});

	it('coalesces: a request made while one is in flight replaces any earlier pending one', async () => {
		let release!: (v: any) => void;
		const gate = new Promise((r) => { release = r; });
		const f = vi.fn(async (_u: any, init: any) => {
			const n = new Float32Array(init.body)[0];
			if (n === 1) await gate;
			return { ok: true, status: 200, json: async () => ({ ...REPLY, fs: n }) } as any;
		});
		vi.stubGlobal('fetch', f);
		const c = createSpectrumClient('http://x', { minIntervalMs: 0 });
		const replies: any[] = [];
		c.onReply = (r) => replies.push(r);

		c.request({ fs: 1, names: ['Fz'], samples: new Float32Array([1]) });   // in flight, gated
		c.request({ fs: 2, names: ['Fz'], samples: new Float32Array([2]) });   // pending
		c.request({ fs: 3, names: ['Fz'], samples: new Float32Array([3]) });   // replaces #2
		release(null);
		await c.flush();

		expect(f).toHaveBeenCalledTimes(2);
		expect(replies.map((r) => r.fs)).toEqual([1, 3]);   // #2 was dropped, never sent
	});

	it('surfaces an error without stalling later requests', async () => {
		const f = vi.fn()
			.mockResolvedValueOnce({ ok: false, status: 503, text: async () => 'down' } as any)
			.mockResolvedValue({ ok: true, status: 200, json: async () => REPLY } as any);
		vi.stubGlobal('fetch', f);
		const c = createSpectrumClient('http://x', { minIntervalMs: 0 });
		const errs: Error[] = []; const replies: any[] = [];
		c.onError = (e) => errs.push(e);
		c.onReply = (r) => replies.push(r);

		c.request(req());
		await c.flush();
		expect(errs).toHaveLength(1);

		c.request(req());
		await c.flush();
		expect(replies).toEqual([REPLY]);
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/force-app/web && npm test -- spectrum
```
Expected: FAIL — cannot resolve `./spectrum`.

- [ ] **Step 3: Implement `spectrum.ts`**

```ts
// Playback FFT transport. Spectra are computed by the recorder sidecar's /dsp/spectrum, which
// runs the SAME scipy welch_spectra() the live recording path uses — so a replayed cut's FFT is
// bit-identical to a live one's rather than a second implementation that could drift.
//
// Two behaviours make a few-per-second call affordable while scrubbing:
//   throttle  — at most one call per minIntervalMs (300 by default, matching the backend's own
//               live-FFT throttle in session._update_fft)
//   coalesce  — while a call is in flight only the NEWEST pending request survives, so dragging
//               the scrub bar can never build a queue of stale windows to work through.

export interface SpectrumReply { fs: number; f: number[]; spectra: Record<string, number[]> }
export interface SpectrumRequest {
	fs: number;
	names: string[];
	samples: Float32Array;   // channel-major, names.length * n
	nperseg?: number;
	force?: boolean;         // bypass the throttle (scrub release)
}
export interface SpectrumClient {
	request(req: SpectrumRequest): void;
	onReply: (r: SpectrumReply) => void;
	onError: (e: Error) => void;
	flush(): Promise<void>;  // settle all in-flight + pending work (tests, and dispose)
	dispose(): void;
}

export function createSpectrumClient(baseUrl: string, opts: { minIntervalMs?: number } = {}): SpectrumClient {
	const minInterval = opts.minIntervalMs ?? 300;
	let pending: SpectrumRequest | null = null;
	let inFlight: Promise<void> | null = null;
	let lastSent = -Infinity;
	let disposed = false;

	const c: SpectrumClient = {
		onReply: () => {},
		onError: () => {},
		request(req) {
			if (disposed) return;
			if (!req.force && !inFlight && performance.now() - lastSent < minInterval) return;
			pending = req;                       // newest wins; an older pending one is discarded
			if (!inFlight) inFlight = pump();
		},
		async flush() {
			while (inFlight) await inFlight;
		},
		dispose() { disposed = true; pending = null; },
	};

	async function pump(): Promise<void> {
		while (pending && !disposed) {
			const req = pending;
			pending = null;
			lastSent = performance.now();
			try {
				const q = new URLSearchParams({ fs: String(req.fs), names: req.names.join(',') });
				if (req.nperseg) q.set('nperseg', String(req.nperseg));
				const res = await fetch(`${baseUrl}/dsp/spectrum?${q}`, {
					method: 'POST',
					headers: { 'Content-Type': 'application/octet-stream' },
					// Send the exact bytes: a subarray view would post the whole backing buffer.
					body: req.samples.slice().buffer,
				});
				if (!res.ok) throw new Error(`spectrum: ${res.status} ${(await res.text()).slice(0, 200)}`);
				if (!disposed) c.onReply(await res.json());
			} catch (e: any) {
				if (!disposed) c.onError(e instanceof Error ? e : new Error(String(e)));
			}
		}
		inFlight = null;
	}

	return c;
}
```

- [ ] **Step 4: Run the tests**

```bash
cd apps/force-app/web && npm test -- spectrum
```
Expected: all 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/force-app/web/src/record/playback/
git commit -m "feat(force-app): throttled, coalescing client for /dsp/spectrum"
```

---

### Task 6: Playback engine

The core. Owns the parsed cache and the playhead, and fills `RecordClient`'s buffers.

**Determinism is the whole design.** A sample's envelope bin and its FRM point are pure functions
of its **index**, never of when it was rendered. That is what makes the seek invariant hold:
buffers after `seek(t)` are identical to buffers after playing straight through to `t`.

**Files:**
- Create: `apps/force-app/web/src/record/playback/engine.ts`
- Test: `apps/force-app/web/src/record/playback/engine.test.ts`

**Interfaces:**
- Consumes: `createSpectrumClient` (Task 5); `Cache` and `parseCache` from `@d1/force-plotting`;
  `RecordClient`, `SUB_NAMES` from `../liveClient`.
- Produces:
  - `createPlaybackEngine(client: RecordClient, opts: PlaybackOpts): PlaybackEngine`
  - `interface PlaybackOpts { baseUrl: string; now?: () => number; schedule?: (cb: () => void) => number; cancel?: (h: number) => void }`
    (`now`/`schedule`/`cancel` are injectable so tests drive time without rAF.)
  - `interface PlaybackEngine { load(cache: Cache, o: { ppr: number; stride: number }): void; play(): void; pause(): void; toggle(): void; seek(tSec: number, o?: { commit?: boolean }): void; setSpeed(x: number): void; dispose(): void; state: PlaybackState }`
  - `interface PlaybackState { loaded: boolean; playing: boolean; tSec: number; duration: number; speed: number; error: string | null }` — a Vue `reactive`, so `TransportBar` (Task 7) binds it directly.
  - `seek(t, { commit: false })` is a drag-in-progress seek (no spectrum request);
    `commit: true` (the default) is a settled seek and forces one.

- [ ] **Step 1: Write the failing test**

Create `apps/force-app/web/src/record/playback/engine.test.ts`:

```ts
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { createPlaybackEngine } from './engine';
import { RecordClient } from '../liveClient';
import type { Cache } from '@d1/force-plotting';

// A synthetic cut: 10 s at 100 Hz, constant 600 rpm (=10 rev/s), cut starts at t=0.
function makeCache(n = 1000, fs = 100): Cache {
	const t = new Float32Array(n), Fx = new Float32Array(n), Fy = new Float32Array(n);
	const Fz = new Float32Array(n), rpm = new Float32Array(n), revs = new Float32Array(n);
	for (let i = 0; i < n; i++) {
		t[i] = i / fs;
		Fx[i] = i; Fy[i] = -i; Fz[i] = Math.sin(i / 10) * 100;
		rpm[i] = 600; revs[i] = (600 / 60) * (i / fs);
	}
	return { N: n, Fs: fs, feed: 0.1, diam: 80, csSec: 0, ceSec: (n - 1) / fs, t, Fx, Fy, Fz, rpm, revs };
}

// Deterministic clock + manual frame pump, so no rAF and no wall-clock flake.
function harness() {
	let clock = 0;
	const frames: (() => void)[] = [];
	const client = new RecordClient();
	const engine = createPlaybackEngine(client, {
		baseUrl: 'http://x',
		now: () => clock,
		schedule: (cb) => { frames.push(cb); return frames.length; },
		cancel: () => {},
	});
	const tick = (ms: number) => { clock += ms; const f = frames.shift(); f?.(); };
	return { client, engine, tick, get clock() { return clock; } };
}

beforeEach(() => { vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ fs: 100, f: [], spectra: {} }) }) as any)); });
afterEach(() => { vi.unstubAllGlobals(); });

describe('playback engine', () => {
	it('loads a cache and reports its duration without playing', () => {
		const h = harness();
		h.engine.load(makeCache(), { ppr: 1, stride: 1 });
		expect(h.engine.state.loaded).toBe(true);
		expect(h.engine.state.duration).toBeCloseTo(9.99, 2);
		expect(h.engine.state.playing).toBe(false);
		expect(h.engine.state.tSec).toBe(0);
	});

	it('advances the playhead by elapsed x speed', () => {
		const h = harness();
		h.engine.load(makeCache(), { ppr: 1, stride: 1 });
		h.engine.play();
		h.tick(1000);
		expect(h.engine.state.tSec).toBeCloseTo(1.0, 2);
		h.engine.setSpeed(2);
		h.tick(1000);
		expect(h.engine.state.tSec).toBeCloseTo(3.0, 2);
	});

	it('pause freezes the playhead across elapsed time', () => {
		const h = harness();
		h.engine.load(makeCache(), { ppr: 1, stride: 1 });
		h.engine.play(); h.tick(1000);
		h.engine.pause();
		const at = h.engine.state.tSec;
		h.tick(5000);
		expect(h.engine.state.tSec).toBe(at);
	});

	it('SEEK INVARIANT: buffers after seek(t) equal buffers after playing to t', () => {
		const played = harness();
		played.engine.load(makeCache(), { ppr: 1, stride: 1 });
		played.engine.play();
		for (let i = 0; i < 5; i++) played.tick(1000);   // play through to t=5
		played.engine.pause();

		const sought = harness();
		sought.engine.load(makeCache(), { ppr: 1, stride: 1 });
		sought.engine.seek(played.engine.state.tSec);

		expect(sought.client.frm.count).toBe(played.client.frm.count);
		expect(sought.client.frm.xy.slice(0, played.client.frm.count * 2))
			.toEqual(played.client.frm.xy.slice(0, played.client.frm.count * 2));
		expect(sought.client.trace.t).toEqual(played.client.trace.t);
		expect(sought.client.trace.fz).toEqual(played.client.trace.fz);
	});

	it('seeking backwards truncates rather than appending', () => {
		const h = harness();
		h.engine.load(makeCache(), { ppr: 1, stride: 1 });
		h.engine.seek(8);
		const far = h.client.frm.count;
		h.engine.seek(2);
		expect(h.client.frm.count).toBeLessThan(far);
		expect(h.engine.state.tSec).toBe(2);
	});

	it('clamps seeks to [0, duration]', () => {
		const h = harness();
		h.engine.load(makeCache(), { ppr: 1, stride: 1 });
		h.engine.seek(-5);
		expect(h.engine.state.tSec).toBe(0);
		h.engine.seek(9999);
		expect(h.engine.state.tSec).toBeCloseTo(h.engine.state.duration, 5);
	});

	it('stops at the end and reports not playing', () => {
		const h = harness();
		h.engine.load(makeCache(), { ppr: 1, stride: 1 });
		h.engine.play();
		for (let i = 0; i < 15; i++) h.tick(1000);
		expect(h.engine.state.playing).toBe(false);
		expect(h.engine.state.tSec).toBeCloseTo(h.engine.state.duration, 5);
	});

	it('trims the trace to windowSec, like the live path', () => {
		const h = harness();
		h.client.windowSec = 2;
		h.engine.load(makeCache(), { ppr: 1, stride: 1 });
		h.engine.seek(9);
		const t = h.client.trace.t;
		expect(t[0]).toBeGreaterThanOrEqual(9 - 2 - 0.5);
	});

	it('reports running peaks and rpm from the cache, not re-derived', () => {
		const h = harness();
		h.engine.load(makeCache(), { ppr: 1, stride: 1 });
		h.engine.seek(5);
		expect(h.client.status.rpm).toBeCloseTo(600, 5);
		expect(h.client.status.peaks.Fx).toBeGreaterThan(0);
		expect(h.client.status.tSec).toBeCloseTo(5, 5);
	});

	it('rejects a degenerate cache instead of dividing by zero', () => {
		const h = harness();
		const bad = { ...makeCache(1), N: 1 } as Cache;
		h.engine.load(bad, { ppr: 1, stride: 1 });
		expect(h.engine.state.loaded).toBe(false);
		expect(h.engine.state.error).toBeTruthy();
	});

	it('makes no network call other than the spectrum request', () => {
		const h = harness();
		h.engine.load(makeCache(), { ppr: 1, stride: 1 });
		h.engine.seek(5);
		for (const call of (globalThis.fetch as any).mock.calls) {
			expect(String(call[0])).toContain('/dsp/spectrum');
		}
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/force-app/web && npm test -- engine
```
Expected: FAIL — cannot resolve `./engine`.

- [ ] **Step 3: Implement `engine.ts`**

```ts
// Video-style playback of an archived cut. The playhead lives here, in the browser, and fills the
// SAME RecordClient buffers the live WebSocket fills — so every panel renders a replay exactly as
// it renders a live recording, with no panel changes at all.
//
// Nothing is written to disk and no RecordingSession is opened: playback is a viewer, not a
// recording. That is also what makes scrubbing possible — RawWriter is append-only and
// FrmIntegrator carries theta/rho across chunks, so seeking backwards through a real session
// would either corrupt the capture or need integrator state unwound that was never built to unwind.
//
// DETERMINISM: a sample's envelope bin and its FRM point are pure functions of its INDEX, never of
// when it was drawn. That is the whole trick — it makes "seek to t" and "play through to t"
// produce byte-identical buffers, which is the invariant engine.test.ts pins down.
import { reactive } from 'vue';
import type { Cache } from '@d1/force-plotting';
import { SUB_NAMES, type RecordClient } from '../liveClient';
import { createSpectrumClient, type SpectrumClient } from './spectrum';

export interface PlaybackOpts {
	baseUrl: string;
	now?: () => number;
	schedule?: (cb: () => void) => number;
	cancel?: (h: number) => void;
}
export interface PlaybackState {
	loaded: boolean; playing: boolean; tSec: number; duration: number; speed: number; error: string | null;
}
export interface PlaybackEngine {
	load(cache: Cache, o: { ppr: number; stride: number }): void;
	play(): void; pause(): void; toggle(): void;
	seek(tSec: number, o?: { commit?: boolean }): void;
	setSpeed(x: number): void;
	dispose(): void;
	state: PlaybackState;
}

// Envelope bins per second of CUT time. Fixed in cut time (not wall time) so the plot has the same
// density at 0.25x as at 20x, and so bin boundaries fall on fixed sample indices.
const BINS_PER_SEC = 200;
// Trailing window handed to /dsp/spectrum, capped like session.py's _fft_cap.
const FFT_WINDOW_SEC = 1.0;
const FFT_MAX = 200_000;

export function createPlaybackEngine(client: RecordClient, opts: PlaybackOpts): PlaybackEngine {
	const now = opts.now ?? (() => performance.now());
	const schedule = opts.schedule ?? ((cb: () => void) => requestAnimationFrame(cb));
	const cancel = opts.cancel ?? ((h: number) => cancelAnimationFrame(h));

	const state = reactive<PlaybackState>({
		loaded: false, playing: false, tSec: 0, duration: 0, speed: 1, error: null,
	});

	let cache: Cache | null = null;
	let ppr = 1, stride = 1;
	let csIdx = 0, revsCs = 0;         // FRM spiral origin (cache's own detected cut start)
	let binSize = 1;                   // samples per envelope bin
	let cursor = 0;                    // exclusive sample index already rendered
	let frame: number | null = null;
	let lastTick = 0;
	const spectra: SpectrumClient = createSpectrumClient(opts.baseUrl);
	spectra.onReply = (r) => {
		if (!r.f.length) return;
		client.fft = { axis: 'Fz', f: r.f, amp: r.spectra.Fz ?? [], fs: r.fs, spectra: r.spectra };
		client.fftFreq = r.f;
		client.fftHistory.push({ t: state.tSec, spectra: r.spectra });
		if (client.fftHistory.length > client.fftHistCap) client.fftHistory.shift();
		client.fftSeq.value++;
	};
	spectra.onError = (e) => { state.error = e.message; };

	function idxOfTime(sec: number): number {
		if (!cache) return 0;
		const t = cache.t;
		let lo = 0, hi = cache.N - 1;
		if (sec <= t[0]) return 0;
		if (sec >= t[hi]) return cache.N;
		while (lo < hi) { const m = (lo + hi) >> 1; if (t[m] < sec) lo = m + 1; else hi = m; }
		return lo;
	}

	function load(c: Cache, o: { ppr: number; stride: number }) {
		reset();
		if (!c || c.N < 2 || !(c.Fs > 0)) {
			state.loaded = false;
			state.error = 'this cut has too few samples to play';
			return;
		}
		cache = c;
		ppr = o.ppr > 0 ? o.ppr : 1;
		stride = Math.max(1, Math.round(o.stride) || 1);
		csIdx = idxOfTime(c.csSec);
		revsCs = c.revs[csIdx] ?? 0;
		binSize = Math.max(1, Math.round(c.Fs / BINS_PER_SEC));
		state.loaded = true;
		state.error = null;
		state.duration = c.t[c.N - 1];
		state.tSec = 0;
		renderTo(0, false);
	}

	function reset() {
		pause();
		client.reset();
		cursor = 0;
		state.tSec = 0; state.duration = 0; state.loaded = false; state.error = null;
		cache = null;
	}

	// Append samples [i0, i1) to the trace envelope and the FRM cloud. Bin boundaries are fixed
	// multiples of binSize, so this is index-deterministic no matter how the range is chopped up.
	function appendRange(i0: number, i1: number) {
		if (!cache || i1 <= i0) return;
		const c = cache;
		const rho0 = c.diam / 2;
		for (let b0 = Math.floor(i0 / binSize) * binSize; b0 < i1; b0 += binSize) {
			const s = Math.max(b0, i0), e = Math.min(b0 + binSize, i1);
			if (e <= s) continue;
			let fxlo = Infinity, fxhi = -Infinity, fylo = Infinity, fyhi = -Infinity, fzlo = Infinity, fzhi = -Infinity;
			for (let i = s; i < e; i++) {
				const x = c.Fx[i], y = c.Fy[i], z = c.Fz[i];
				if (x < fxlo) fxlo = x; if (x > fxhi) fxhi = x;
				if (y < fylo) fylo = y; if (y > fyhi) fyhi = y;
				if (z < fzlo) fzlo = z; if (z > fzhi) fzhi = z;
			}
			client.trace.t.push(c.t[(s + e - 1) >> 1]);
			client.trace.fx.push([fxlo, fxhi]);
			client.trace.fy.push([fylo, fyhi]);
			client.trace.fz.push([fzlo, fzhi]);
			// The cache carries summed axes only. Sub-channels are the same synthetic split
			// ReplaySource applies server-side (Fx/2, Fy/2, Fz/4); Tacho has no counterpart at all
			// and stays flat — TransportBar labels this so it is never mistaken for real data.
			const sub = client.trace.sub;
			sub.Fx1.push([fxlo / 2, fxhi / 2]); sub.Fx2.push([fxlo / 2, fxhi / 2]);
			sub.Fy1.push([fylo / 2, fyhi / 2]); sub.Fy2.push([fylo / 2, fyhi / 2]);
			for (const k of ['Fz1', 'Fz2', 'Fz3', 'Fz4']) sub[k].push([fzlo / 4, fzhi / 4]);
			sub.Tacho.push([0, 0]);
		}
		// FRM: geometry is a pure function of the sample index given the fixed spiral origin, so
		// this matches liveCloud's `measured` branch exactly and needs no carried state.
		const F = c.feed;
		let n = client.frm.count;
		const first = Math.max(i0, csIdx);
		const off = first - ((first - csIdx) % stride);
		for (let i = Math.max(off, csIdx); i < i1; i += stride) {
			if (i < i0) continue;
			const r = (c.revs[i] - revsCs) / ppr;
			const rho = rho0 - F * r;
			if (rho < 0) break;
			const th = 2 * Math.PI * r;
			client.frm.xy[n * 2] = rho * Math.cos(th);
			client.frm.xy[n * 2 + 1] = rho * Math.sin(th);
			const col = c[axisKey()][i];
			client.frm.c[n] = col;
			const a = Math.abs(col);
			if (a > client.frm.cAbsMax) client.frm.cAbsMax = a;
			n++;
		}
		client.frm.count = n;
	}

	function axisKey(): 'Fx' | 'Fy' | 'Fz' { return 'Fz'; }

	function trimWindow(tSec: number) {
		const tMin = tSec - client.windowSec;
		let drop = 0;
		const t = client.trace.t;
		while (drop < t.length && t[drop] < tMin) drop++;
		if (drop <= 0) return;
		client.trace.t.splice(0, drop);
		client.trace.fx.splice(0, drop);
		client.trace.fy.splice(0, drop);
		client.trace.fz.splice(0, drop);
		for (const n of SUB_NAMES) client.trace.sub[n].splice(0, drop);
	}

	// Bring the buffers to exactly represent playhead `tSec`. Forward is an append; backward
	// rebuilds from scratch, which is cheap because it is a straight pass over typed arrays.
	function renderTo(tSec: number, requestSpectrum = true, forceSpectrum = false) {
		if (!cache) return;
		const target = idxOfTime(tSec);
		if (target < cursor) {
			client.trace = emptyTrace();
			client.frm.count = 0; client.frm.cAbsMax = 1;
			client.status.peaks = { Fx: 0, Fy: 0, Fz: 0 };
			cursor = 0;
		}
		appendRange(cursor, target);
		cursor = target;
		trimWindow(tSec);

		const c = cache;
		const last = Math.max(0, Math.min(c.N - 1, target - 1));
		let px = client.status.peaks.Fx, py = client.status.peaks.Fy, pz = client.status.peaks.Fz;
		for (let i = Math.max(0, target - 1); i < target; i++) {
			px = Math.max(px, Math.abs(c.Fx[i])); py = Math.max(py, Math.abs(c.Fy[i])); pz = Math.max(pz, Math.abs(c.Fz[i]));
		}
		client.status.peaks = { Fx: px, Fy: py, Fz: pz };
		client.status.tSec = tSec;
		client.status.rpm = c.rpm[last];        // straight from the cache; never re-derived
		client.status.nTotal = target;
		client.frameSeq.value++;

		if (requestSpectrum) {
			const win = Math.min(Math.round(c.Fs * FFT_WINDOW_SEC), FFT_MAX);
			const s0 = Math.max(0, target - win);
			if (target - s0 >= 256) {
				const n = target - s0;
				const buf = new Float32Array(n * 3);
				buf.set(c.Fx.subarray(s0, target), 0);
				buf.set(c.Fy.subarray(s0, target), n);
				buf.set(c.Fz.subarray(s0, target), n * 2);
				spectra.request({ fs: c.Fs, names: ['Fx', 'Fy', 'Fz'], samples: buf, force: forceSpectrum });
			}
		}
	}

	function emptyTrace() {
		const sub: Record<string, [number, number][]> = {};
		for (const n of SUB_NAMES) sub[n] = [];
		return { t: [] as number[], fx: [] as [number, number][], fy: [] as [number, number][], fz: [] as [number, number][], sub };
	}

	function tick() {
		frame = null;
		if (!state.playing || !cache) return;
		const t = now();
		const dt = (t - lastTick) / 1000;
		lastTick = t;
		const next = state.tSec + dt * state.speed;
		if (next >= state.duration) {
			state.tSec = state.duration;
			renderTo(state.duration, true, true);
			pause();
			return;
		}
		state.tSec = next;
		renderTo(next);
		frame = schedule(tick);
	}

	function play() {
		if (!state.loaded || state.playing) return;
		if (state.tSec >= state.duration) { state.tSec = 0; renderTo(0, false); }
		state.playing = true;
		// Panels gate live accumulation on state === 'recording' (see RpmPanel); playback is live
		// data as far as they are concerned. Pausing drops back to 'idle', which is also why the
		// Save dialog never fires — RecordPage only opens it on recording -> finalizing/done/error.
		client.status.state = 'recording';
		lastTick = now();
		frame = schedule(tick);
	}

	function pause() {
		state.playing = false;
		client.status.state = 'idle';
		if (frame !== null) { cancel(frame); frame = null; }
	}

	return {
		state,
		load,
		play,
		pause,
		toggle() { state.playing ? pause() : play(); },
		seek(tSec, o) {
			if (!state.loaded) return;
			const t = Math.max(0, Math.min(state.duration, tSec));
			state.tSec = t;
			renderTo(t, true, o?.commit !== false);
			lastTick = now();
		},
		setSpeed(x) { state.speed = x > 0 ? x : 1; },
		dispose() { pause(); spectra.dispose(); cache = null; },
	};
}
```

- [ ] **Step 4: Run the tests**

```bash
cd apps/force-app/web && npm test -- engine
```
Expected: all 11 PASS. If the seek-invariant test fails, the cause is non-determinism in
`appendRange` — check that bin boundaries are computed from `Math.floor(i / binSize) * binSize`
and the FRM loop's start index from `csIdx`, never from `cursor`.

- [ ] **Step 5: Typecheck and commit**

```bash
cd apps/force-app/web && npm run typecheck
git add apps/force-app/web/src/record/playback/
git commit -m "feat(force-app): playback engine with deterministic seek"
```

---

### Task 7: Transport bar

**Files:**
- Create: `apps/force-app/web/src/record/panels/TransportBar.vue`

**Interfaces:**
- Consumes: `PlaybackState` and the engine methods (Task 6), via `useWorkspace()` (Task 8 adds
  `w.playback`). Because Task 8 has not landed yet, this task ends with the component built and
  typechecking but not yet mounted; Task 8 mounts it.
- Produces: `<TransportBar />`, no props — reads `w.playback` from the workspace.

- [ ] **Step 1: Write the component**

```vue
<script setup lang="ts">
// Video-style transport for replaying an archived cut: play/pause, a scrub bar, an elapsed /
// total readout and a speed picker. Playback writes nothing — this drives a playhead over a cut
// already in the database, so there is no Stop and no Save.
import { computed } from 'vue';
import { useWorkspace } from '../workspace';

const w = useWorkspace();
const p = computed(() => w.playback.state);

// Scrubbing fires continuously while dragging; only the settled value forces a spectrum request
// (the FFT / spectrogram views are the expensive part). `input` = dragging, `change` = released.
function onScrub(e: Event) { w.playback.seek(Number((e.target as HTMLInputElement).value), { commit: false }); }
function onScrubEnd(e: Event) { w.playback.seek(Number((e.target as HTMLInputElement).value), { commit: true }); }

const SPEEDS = [0.25, 0.5, 1, 2, 5, 10, 20];
function fmt(sec: number): string {
	if (!Number.isFinite(sec) || sec < 0) return '0:00';
	const m = Math.floor(sec / 60);
	return `${m}:${String(Math.floor(sec % 60)).padStart(2, '0')}`;
}
</script>

<template>
	<div class="transport">
		<div class="row">
			<button class="play" :disabled="!p.loaded" :title="p.playing ? 'Pause' : 'Play'" @click="w.playback.toggle()">
				<span class="material-symbols-rounded">{{ p.playing ? 'pause' : 'play_arrow' }}</span>
			</button>
			<input class="scrub" type="range" min="0" :max="p.duration || 0" step="0.01"
				:value="p.tSec" :disabled="!p.loaded" @input="onScrub" @change="onScrubEnd" />
			<span class="time">{{ fmt(p.tSec) }} / {{ fmt(p.duration) }}</span>
		</div>
		<div class="row sub">
			<label class="speed">Speed
				<select :value="p.speed" @change="w.playback.setSpeed(Number(($event.target as HTMLSelectElement).value))">
					<option v-for="s in SPEEDS" :key="s" :value="s">{{ s }}×</option>
				</select>
			</label>
			<span class="note" title="This file stores summed Fx/Fy/Fz only. Per-sensor sub-channels are shown as an even split, and Tacho is not stored at all — RPM comes from the file's own rpm series.">
				<span class="material-symbols-rounded">info</span> summed axes only
			</span>
		</div>
		<p v-if="p.error" class="err">{{ p.error }}</p>
		<p v-else-if="!p.loaded" class="hint">Pick a cut above to load it.</p>
	</div>
</template>

<style scoped>
.transport { display: flex; flex-direction: column; gap: 7px; padding: 9px 0 2px; border-top: 1px solid var(--border); }
.row { display: flex; align-items: center; gap: 9px; }
.row.sub { justify-content: space-between; }
.play { display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 34px; flex-shrink: 0;
	background: #22c55e; color: #05210f; border: none; border-radius: 50%; cursor: pointer; }
.play:disabled { opacity: 0.5; cursor: not-allowed; }
.play .material-symbols-rounded { font-size: 21px; }
.scrub { flex: 1; min-width: 0; accent-color: var(--accent); cursor: pointer; }
.scrub:disabled { opacity: 0.5; cursor: not-allowed; }
.time { font-size: 11.5px; font-family: var(--mono); color: var(--text-dim); font-variant-numeric: tabular-nums; flex-shrink: 0; }
.speed { display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--text-dim); margin: 0; }
.speed select { width: auto; margin: 0; padding: 4px 7px; font-size: 12px; }
.note { display: inline-flex; align-items: center; gap: 4px; font-size: 10.5px; color: var(--text-dim); cursor: help; }
.note .material-symbols-rounded { font-size: 14px; }
.err { color: var(--danger); font-size: 12px; margin: 2px 0 0; }
.hint { font-size: 11.5px; color: var(--text-dim); margin: 2px 0 0; }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add apps/force-app/web/src/record/panels/TransportBar.vue
git commit -m "feat(force-app): playback transport bar"
```

---

### Task 8: Wire playback into the workspace

**Files:**
- Modify: `apps/force-app/web/src/record/workspace.ts`
- Modify: `apps/force-app/web/src/record/panels/RecordingOptions.vue:103-116, 146-155`
- Modify: `apps/force-app/web/src/record/RecordPage.vue:113-122`

**Interfaces:**
- Consumes: `createPlaybackEngine` (Task 6), `TransportBar` (Task 7).
- Produces on the workspace: `mode: ComputedRef<'record' | 'playback'>` and `playback: PlaybackEngine`.

- [ ] **Step 1: Add mode + engine to `workspace.ts`**

Add imports:

```ts
import { createPlaybackEngine } from './playback/engine';
```

After the `replay` reactive declaration, add:

```ts
	// Replaying an archived cut is PLAYBACK, not recording: a local playhead over a cut already in
	// the database, writing nothing to disk. Making the mode explicit (rather than testing
	// source.value === 'replay' at each site) keeps the "playback writes nothing" guarantee in one
	// auditable place.
	const mode = computed<'record' | 'playback'>(() => (source.value === 'replay' ? 'playback' : 'record'));
	const playback = createPlaybackEngine(client, { baseUrl: client.baseUrl });
	watch(() => replay.speed, (s) => playback.setSpeed(s), { immediate: true });
```

Change the `replay` default speed from `20` to `1`:

```ts
	const replay = reactive<{ query: string; options: ReplayOption[]; cacheId: string; label: string; speed: number; loading: boolean }>(
		{ query: '', options: [], cacheId: '', label: '', speed: 1, loading: false },
	);
```

- [ ] **Step 2: Stop alarms firing on an archived cut**

Replace the alarm watch:

```ts
	// Record mode only: an archived cut must never trip a safety alarm on a machine that is not
	// cutting. Playback drove this with RPM that was also wrong by the decimation stride, so every
	// replay raised the full-screen overlay.
	watch(() => client.frameSeq.value, () => {
		if (mode.value === 'record' && st.state === 'recording') alarms.evaluate(st.peaks, st.rpm, cfg.rpm);
	});
```

- [ ] **Step 3: Load the cut into the engine on pick**

In `pickReplayCut`, replace the first two lines with a load, and hydrate `cfg` from the operation
so the RPM gauge target and the FRM scale mean something:

```ts
	async function pickReplayCut(o: ReplayOption) {
		replay.cacheId = o.cacheId; replay.label = o.label;
		errMsg.value = null;
		// Parse the cut locally and hand it to the playhead. No backend session is opened and
		// nothing is written to disk — playback is a viewer over a cut already in the database.
		try {
			const res = await api.get(`/assets/${o.cacheId}`, { responseType: 'arraybuffer' });
			const c = parseCache(res.data as ArrayBuffer);
			playback.load(c, { ppr: cfg.ppr, stride: plot.liveFrmStride });
			cfg.feed = c.feed; cfg.diam = c.diam; cfg.sample_rate = c.Fs;
		} catch (e: any) {
			errMsg.value = `could not load that cut — ${e?.message || e}`;
		}
		if (!o.operationId) return;
```

Inside the metadata hydration, after `meta.op_type = ...`, add:

```ts
			// The RPM gauge's target and the alarm threshold both read cfg.rpm; without this a
			// replayed cut was measured against whatever was left in the form.
			if (d.machining_spindle_speed_rpm != null) cfg.rpm = Number(d.machining_spindle_speed_rpm);
```

Add `parseCache` to the existing `@d1/force-plotting` import.

- [ ] **Step 4: Make `start()` refuse to record a replay**

Replace the `if (source.value === 'replay')` branch in `start()`:

```ts
			if (source.value === 'replay') {
				// Playback is driven by the transport bar, not by start(). Reaching here means a
				// caller bypassed the mode switch.
				throw new Error('replay is played, not recorded — use the transport controls');
			}
```

Remove the now-unused `client.startReplay` import usage; leave `startReplay` on `RecordClient`
itself, since `/record/start_replay` remains a supported backend entry point.

- [ ] **Step 5: Export the new surface**

Add `mode, playback,` to the returned object in `createWorkspace`.

- [ ] **Step 6: Swap Start/Stop for the transport in `RecordingOptions.vue`**

Add the import: `import TransportBar from './TransportBar.vue';`

Replace the `Replay speed ×` label (line 115) with nothing — speed now lives in the transport bar.

Replace the `<div class="actions">` block with:

```html
		<!-- ─── Actions ─── -->
		<TransportBar v-if="w.mode.value === 'playback'" />
		<div v-else class="actions">
			<button v-if="!w.locked.value" class="btn start" :disabled="w.busy.value || !w.st.connected" @click="w.start()">
				<span class="material-symbols-rounded">fiber_manual_record</span> Start
			</button>
			<button v-else class="btn stop" :disabled="w.busy.value || w.isFinalizing.value" @click="w.stop()">
				<span class="material-symbols-rounded">stop</span> {{ w.isFinalizing.value ? 'Finalizing…' : 'Stop' }}
			</button>
			<button v-if="w.isDone.value" class="btn ghost" @click="w.newRun()">New</button>
		</div>
```

The cut list's `:disabled="w.locked.value"` already prevents switching cuts mid-play, since
`play()` sets `status.state = 'recording'`.

- [ ] **Step 7: Keep the Save dialog out of playback in `RecordPage.vue`**

```ts
watch(() => st.state, async (s, prev) => {
	// Playback never finalizes anything, so there is nothing to save — and its state only ever
	// moves recording <-> idle, which would not match here anyway. Guarded explicitly so it stays
	// true if playback's state handling changes.
	if (w.mode.value === 'playback') return;
	if ((s === 'finalizing' || s === 'done' || s === 'error') && prev === 'recording') {
		w.saveOpen.value = true;
	}
	if (s === 'done' && prev !== 'done' && !w.finishedCache.value) {
		await w.loadFinished();
	}
});
```

Add `w.playback.dispose();` to `onBeforeUnmount`.

- [ ] **Step 8: Typecheck, test, and verify by hand**

```bash
cd apps/force-app/web && npm run typecheck && npm test
```

Then start the backend and the web dev server, open Recording, choose **Replay file**, pick a cut
and confirm all of:

- Play runs the cut through the viewers at true realtime (1x default).
- Pause freezes; Play resumes from the same point.
- Dragging the scrub bar moves both the waveform and the FRM spiral, forwards and backwards.
- The RPM gauge reads the cut's real RPM, and **no** safety-alarm overlay appears.
- No Save dialog appears at the end, and no new capture shows up in `backend/captures/`.

- [ ] **Step 9: Commit**

```bash
git add apps/force-app/web/src/record/
git commit -m "feat(force-app): replay plays as video, not a re-recording"
```

---

### Task 9: Update the changelog

**Files:**
- Modify: `apps/force-app/web/src/changelog.ts`

- [ ] **Step 1: Add the entry**

Entries are `{ version, date, notes: string[] }`, newest first, and the file's own header says to
add one with any release that bumps `apps/force-app/desktop/package.json`.

**Note a pre-existing gap before you start:** the changelog's newest entry is `0.1.6` while
`desktop/package.json` is already at `0.1.8`. Do not invent notes for 0.1.7 or 0.1.8 — you do not
know what shipped in them. Add `0.1.9` on top, bump `desktop/package.json` to `0.1.9`, and mention
the 0.1.7/0.1.8 gap to the maintainer rather than silently closing it.

```ts
	{
		version: '0.1.9',
		date: '2026-08-27',
		notes: [
			'Replay file now plays like a video: play, pause and scrub through a past cut, at true realtime speed by default (with slow-motion down to 0.25×). It drives the same waveform, FFT, FRM and RPM views a live cut does.',
			'Replaying a cut no longer records a second copy of it — it plays the file already in the database, so nothing new is written to disk.',
			'Fixed: replaying a long cut reported a spindle speed several times too high, which also raised a false safety alarm every time.',
			'Fixed: replay ignored the speed you asked for on long cuts, always finishing in about 40 seconds however long the cut really was.',
		],
	},
```

- [ ] **Step 2: Verify and commit**

```bash
cd apps/force-app/web && npm run typecheck
git add apps/force-app/web/src/changelog.ts apps/force-app/desktop/package.json
git commit -m "docs(force-app): changelog for replay playback transport"
```

---

## Self-Review

**Spec coverage**

| Spec requirement | Task |
|---|---|
| Playback is a viewer — no capture, no finalize, no Save dialog | 8 (steps 4, 7) |
| Playhead local, DSP in Python via stateless `/dsp/spectrum` | 3, 4, 5, 6 |
| FRM geometry from `revs`, origin at `csSec` | 6 (`appendRange`) |
| Explicit `mode: 'record' \| 'playback'` | 8 (step 1) |
| No filter chain in playback | (nothing added — verified absent in Task 6) |
| Alarms not evaluated in playback | 8 (step 2) |
| Default speed 1x, slow-motion available | 8 (step 1), 7 (`SPEEDS`) |
| Spectrogram/waterfall rebuild debounced on scrub release | 6 (`commit` flag), 7 (`change` handler) |
| Sub-channels synthetic, Tacho absent, both labelled | 6 (`appendRange`), 7 (`.note`) |
| Sidecar unreachable degrades rather than stops | 6 (`spectra.onError` sets `state.error` only) |
| Backend: `FrmIntegrator` takes `source.rate` | 1 |
| Backend: drop the `min(dt, 0.1)` cap | 2 |
| Test: `/dsp/spectrum` matches `welch_spectra` | 4 |
| Test: seek invariant | 6 |
| Test: decimated-replay RPM | 1 |

**Type consistency** — `SpectrumReply` (Task 5) is consumed in Task 6's `spectra.onReply` with
fields `fs`/`f`/`spectra`, matching the endpoint's response in Task 4. `PlaybackState` field names
(`loaded`/`playing`/`tSec`/`duration`/`speed`/`error`) are used identically in Tasks 6, 7 and 8.
`FrmIntegrator(cfg, fs)` in Task 1 keeps `fs` optional, so the two existing test callers are
untouched.

**Known follow-up, deliberately out of scope:** `client.fft.axis` is hardcoded to `'Fz'` in
Task 6 and the engine always requests `Fx,Fy,Fz`. Per-sub-channel spectra in playback would need
the engine to know the panel's channel selection; the summed axes are what the FFT panel shows by
default. Not required by the spec.
