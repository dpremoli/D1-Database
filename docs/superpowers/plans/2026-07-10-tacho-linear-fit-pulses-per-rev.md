# Tacho Linear Fit + Selectable Pulses-Per-Rev Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `tachorpm`'s RPM fit linear (not smooth) everywhere, and let the user set pulses-per-rev per operation (with a global default), threading it through the canonical MATLAB pipeline, the orchestrator, and the dashboard's Live mode.

**Architecture:** `process_force.m` computes a raw (PPR=1) tacho rate for the live-cache's `revs_cum` geometry, and a real (PPR-divided) rate for everything else (FRM PNGs, `mean_rpm`, `series.json`). `force_crawler_state.pulses_per_rev` is the admin-configurable global default; `machining_force_analysis.pulses_per_rev` is the resolved per-row value the orchestrator writes back after each run (mirroring how `sample_rate`/`feed` are already reported via `summary.json`). Live mode divides the raw cached `revs_cum` by an editable client-side PPR — an O(1) extra division per point, no host round-trip, exactly like Feed/Diameter are already instant client-side parameters.

**Tech Stack:** MATLAB (Signal Processing Toolbox `tachorpm`), Python (`psycopg2`, the existing `force_orchestrator.py`), Vue 3 `<script setup>` (Directus extensions), TypeScript, Postgres/Directus migrations (dbmate), Playwright.

## Global Constraints

- Read-only w.r.t. the archive `.mat` files — `process_force.m` never opens them writable (existing invariant; do not violate it).
- Settings only affect files processed **after** the change — never retroactively rewrite existing `machining_force_analysis` rows' baked PNGs/metrics outside of an explicit reprocess.
- `FitType` is hardcoded to `'linear'` — no UI toggle for it.
- The live cache's binary wire format (`live_cache.bin`, magic `0x44314C43`, 32-byte header + six `float32[N]` arrays) is unchanged — only which values are written into the existing `rpm`/`revs` array slots changes.
- Follow the existing `force_crawler_state` / `machining_force_analysis` migration blueprint exactly (see `db/migrations/20260708000082_force_live_cache.sql` for the two-tables-in-one-migration precedent).

---

### Task 1: Database migration — `pulses_per_rev` columns

**Files:**
- Create: `db/migrations/20260710000085_force_pulses_per_rev.sql`

**Interfaces:**
- Produces: `force_crawler_state.pulses_per_rev INTEGER NOT NULL DEFAULT 1` (global default, read by `force_orchestrator.py`'s `load_sampling_opts`, edited by `d1-force-crawler`'s `Crawler.vue`).
- Produces: `machining_force_analysis.pulses_per_rev INTEGER` (nullable; the value that produced the row's current PNGs/metrics; written by `force_orchestrator.py`'s `ingest`, read/edited by `d1-force-dashboard`'s `ForceDashboard.vue`).

- [ ] **Step 1: Write the migration**

```sql
-- migrate:up
-- Pulses-per-rev for tachorpm (scripts/matlab/process_force.m): the number of
-- tacho pulses per spindle revolution is not always 1. A global admin default
-- (force_crawler_state, following the series_points/live_cache_points
-- blueprint) plus a per-operation resolved value (machining_force_analysis,
-- following the live_cache_file/live_render_points blueprint in migration
-- ...082) — the orchestrator writes the value actually used for each row's
-- current PNGs/metrics back via summary.json, the same way sample_rate/feed
-- already round-trip.

ALTER TABLE force_crawler_state
    ADD COLUMN IF NOT EXISTS pulses_per_rev INTEGER NOT NULL DEFAULT 1;

COMMENT ON COLUMN force_crawler_state.pulses_per_rev IS
    'Global default tacho pulses-per-revolution for tachorpm (PulsesPerRev). Overridable per-row via machining_force_analysis.pulses_per_rev.';

INSERT INTO directus_fields (collection, field, interface, display, options, width, sort, readonly, hidden)
SELECT collection, field, interface, display, options::json, width, sort, readonly, hidden
FROM (VALUES
    ('force_crawler_state', 'pulses_per_rev', 'input', 'raw', NULL, 'half', 11, false, false)
) v(collection, field, interface, display, options, width, sort, readonly, hidden)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS pulses_per_rev INTEGER;

COMMENT ON COLUMN machining_force_analysis.pulses_per_rev IS
    'Tacho pulses-per-revolution actually used to produce this row''s current PNGs/metrics. NULL = never processed under this feature yet.';

INSERT INTO directus_fields (collection, field, interface, display, options, width, sort, readonly, hidden)
SELECT collection, field, interface, display, options::json, width, sort, readonly, hidden
FROM (VALUES
    ('machining_force_analysis', 'pulses_per_rev', 'input', 'raw', NULL, 'half', 22, false, false)
) v(collection, field, interface, display, options, width, sort, readonly, hidden)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- migrate:down
DELETE FROM directus_fields WHERE collection = 'machining_force_analysis' AND field = 'pulses_per_rev';
ALTER TABLE machining_force_analysis DROP COLUMN IF EXISTS pulses_per_rev;
DELETE FROM directus_fields WHERE collection = 'force_crawler_state' AND field = 'pulses_per_rev';
ALTER TABLE force_crawler_state DROP COLUMN IF EXISTS pulses_per_rev;
```

- [ ] **Step 2: Apply the migration (requires a running dev DB + `DATABASE_URL`)**

Run: `make migrate`
Expected: output lists `20260710000085_force_pulses_per_rev.sql` as applied, no errors.

If no dev DB is available in this environment, instead run: `make migrate-status` after manually reviewing the SQL for syntax — note in the task result which verification path was used.

- [ ] **Step 3: Commit**

```bash
git add db/migrations/20260710000085_force_pulses_per_rev.sql
git commit -m "$(cat <<'EOF'
feat(db): add pulses_per_rev to force_crawler_state + machining_force_analysis

Global admin default plus a per-operation resolved value, following the
existing force_crawler_state / machining_force_analysis migration blueprint.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `process_force.m` — linear fit + pulses-per-rev

**Files:**
- Modify: `scripts/matlab/process_force.m:1-42` (header doc + `opts` defaults), `scripts/matlab/process_force.m:103-110` (tacho→rpm), `scripts/matlab/process_force.m:187-205` (revs_cum + summary)

**Interfaces:**
- Consumes: `opts.pulses_per_rev` (new field, default `1`, set by `force_orchestrator.py`'s `matlab_opts_literal`).
- Produces: `summary.pulses_per_rev` (new scalar field in `summary.json`, consumed by `force_orchestrator.py`'s `SUMMARY_COLS`/`ingest`).

- [ ] **Step 1: Add the `opts.pulses_per_rev` default and update the header doc**

In `scripts/matlab/process_force.m`, in the `OPTS` doc block (around line 22), add a line after `live_cache_points`:

```matlab
%       live_cache_points  target point count per axis in live_cache.bin (default 250000)
%       pulses_per_rev  tacho pulses per spindle revolution (default 1)
```

Then in `process_force`, after the existing `withdefault` calls (around line 42):

```matlab
opts = withdefault(opts, 'live_cache_points', 250000);
opts = withdefault(opts, 'pulses_per_rev', 1);
```

- [ ] **Step 2: Split raw vs. real RPM at the `tachorpm` call**

Replace the current RPM block (`scripts/matlab/process_force.m:103-110`):

```matlab
% ---- RPM from tacho (fallback: MaxRPM constant) ----
try
    rpm = tachorpm(double(tacho), Fs);
    rpm = interp1(linspace(0,1,numel(rpm))', rpm(:), linspace(0,1,N)', 'linear', 'extrap');
catch ME
    fprintf('  tachorpm failed (%s); using MaxRPM=%g constant\n', ME.message, MaxRPM);
    rpm = ones(N,1) * MaxRPM;
end
```

with:

```matlab
% ---- RPM from tacho (fallback: MaxRPM constant) ----
%   rpm_raw is at PulsesPerRev=1 (raw pulse-edge rate) — it alone feeds
%   revs_cum below, keeping the live cache's geometry PPR-agnostic so the
%   browser can apply any divisor to it interactively. `rpm` (the real,
%   per-op-corrected rate) feeds everything else: series.json's RPM envelope,
%   the FRM PNG geometry, and mean_rpm.
try
    rpm_raw = tachorpm(double(tacho), Fs, 'FitType', 'linear');
    rpm_raw = interp1(linspace(0,1,numel(rpm_raw))', rpm_raw(:), linspace(0,1,N)', 'linear', 'extrap');
catch ME
    fprintf('  tachorpm failed (%s); using MaxRPM=%g constant\n', ME.message, MaxRPM);
    rpm_raw = ones(N,1) * MaxRPM;
end
rpm = rpm_raw / opts.pulses_per_rev;
```

- [ ] **Step 3: Feed `revs_cum` from `rpm_raw`, not `rpm`**

In `scripts/matlab/process_force.m:187-195`, change the comment and the `revs_cum` line:

```matlab
% ---- live cache: decimated point cloud for the browser's Live mode ----
%   revs_cum (cumulative revolutions from index 1) is integrated at FULL resolution
%   from rpm_raw (PulsesPerRev=1) then decimated — since it is smooth + monotonic,
%   decimation is lossless for client-side reconstruction, and staying
%   PPR-agnostic lets the browser divide by ANY pulses-per-rev interactively.
%   The client rebuilds theta/rho for ANY crop-start cs / Feed / Diam / PPR via:
%   r = (revs_cum(i)-revs_cum(cs))/PPR;  theta = wrapTo2Pi(2*pi*r);
%   rho = Diam/2 - Feed*r.  (An RPM override instead uses r = RPM/60 * t.)
revs_cum = cumsum([0; rpm_raw(2:end) / 60 * dt]);           % turns elapsed at each sample
write_live_cache(fullfile(outdir, 'live_cache.bin'), opts.live_cache_points, ...
    Fs, Feed, Diam, cutstart, abs_cut_end, t, Fx, Fy, Fz, rpm, revs_cum);
```

(Only the `cumsum` source array changes from `rpm` to `rpm_raw`; the `write_live_cache` call is unchanged — it still passes the real `rpm` for the cache's informational `rpm` array.)

- [ ] **Step 4: Report the effective `pulses_per_rev` in `summary.json`**

In `scripts/matlab/process_force.m:198-205`, add `pulses_per_rev` to the `summary` struct:

```matlab
% ---- summary ----
summary = struct( ...
    'status','done', 'message','', 'source',matpath, ...
    'version',ver, 'sample_rate',Fs, 'feed',Feed, 'cut_diameter',Diam, ...
    'surface_speed',SurfSpd, 'depth_of_cut',DoC, 'max_rpm',MaxRPM, 'dyno_gain',gain, ...
    'trigger_time',trigTime, ...
    'n_raw',N, 'cut_start_idx',cutstart, 'cut_end_idx',abs_cut_end, ...
    'peak_fx',max(abs(Fx)), 'peak_fy',max(abs(Fy)), 'peak_fz',max(abs(Fz)), ...
    'mean_rpm',mean(rpm,'omitnan'), 'pulses_per_rev',opts.pulses_per_rev);
```

- [ ] **Step 5: Verify with a syntax check (no MATLAB license needed for this)**

Run: `grep -n "rpm_raw\|pulses_per_rev\|FitType" "scripts/matlab/process_force.m"`
Expected: shows the new `rpm_raw` computation, the `opts.pulses_per_rev` default/usage, the `'FitType', 'linear'` call, and `revs_cum = cumsum([0; rpm_raw(2:end) ...`. Manually re-read the whole function once to confirm `rpm` (not `rpm_raw`) is still what feeds `rpm_c` (FRM geometry, `scripts/matlab/process_force.m:137`) and `series.json` (`scripts/matlab/process_force.m:118`).

If a MATLAB installation + a sample archive `.mat` are available on the host, additionally run:
`matlab -batch "addpath('scripts/matlab'); process_force('<path-to-a-known-good.mat>','<scratch-outdir>',struct('pulses_per_rev',2))"`
Expected: `STATUS=done` printed; `<scratch-outdir>/summary.json` contains `"pulses_per_rev":2` and `"mean_rpm"` is exactly half of a run with `pulses_per_rev=1` on the same file.

- [ ] **Step 6: Commit**

```bash
git add scripts/matlab/process_force.m
git commit -m "$(cat <<'EOF'
feat(force): linear tacho fit + selectable pulses-per-rev

FitType is hardcoded to linear (not exposed as a setting). PulsesPerRev
divides the tacho-derived RPM before it reaches the FRM geometry/metrics,
but the live cache's revs_cum stays at the raw (PPR=1) rate so the
browser's Live mode can apply any PPR divisor interactively.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `force_orchestrator.py` — thread `pulses_per_rev` through

**Files:**
- Modify: `scripts/force_orchestrator.py:78-82` (`SUMMARY_COLS`), `scripts/force_orchestrator.py:186-211` (`claim_batch`), `scripts/force_orchestrator.py:214-238` (`DEFAULT_SAMPLING`/`load_sampling_opts`), `scripts/force_orchestrator.py:253-282` (`process_file`)

**Interfaces:**
- Consumes: `summary.pulses_per_rev` from Task 2's `process_force.m` output.
- Consumes: `force_crawler_state.pulses_per_rev`, `machining_force_analysis.pulses_per_rev` from Task 1's migration.
- Produces: `machining_force_analysis.pulses_per_rev` written on every successful `ingest` (via the existing `SUMMARY_COLS` mechanism — no new ingest code needed).

- [ ] **Step 1: Add `pulses_per_rev` to `SUMMARY_COLS`**

In `scripts/force_orchestrator.py:78-82`, add the new column (no alias needed — MATLAB now emits the same key name as the DB column):

```python
SUMMARY_COLS = [
    "file_version",
    "sample_rate",
    "feed",
    "cut_diameter",
    "surface_speed",
    "depth_of_cut",
    "max_rpm",
    "dyno_gain",
    "n_raw",
    "cut_start_idx",
    "cut_end_idx",
    "peak_fx",
    "peak_fy",
    "peak_fz",
    "mean_rpm",
    "trigger_time",
    "pulses_per_rev",
]
```

This alone makes `ingest()` write `machining_force_analysis.pulses_per_rev` on every successful run — `ingest()` already loops `SUMMARY_COLS` generically (`scripts/force_orchestrator.py:402-417`); no other change to `ingest()` is needed.

- [ ] **Step 2: Add the global default to `DEFAULT_SAMPLING` and `load_sampling_opts`**

In `scripts/force_orchestrator.py:217-218`:

```python
DEFAULT_SAMPLING = {
    "series_points": 3000,
    "fft_points": 3000,
    "frm_downsample_step": 5,
    "frm_dpi": 300,
    "live_cache_points": 250000,
    "pulses_per_rev": 1,
}
```

In `scripts/force_orchestrator.py:221-231` (`load_sampling_opts`), add the column to the query:

```python
def load_sampling_opts(conn) -> dict:
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT series_points, fft_points, frm_downsample_step, frm_dpi, live_cache_points, "
                "pulses_per_rev FROM force_crawler_state WHERE id='00000000-0000-0000-0000-000000000001'"
            )
            row = cur.fetchone()
        if row:
            return {k: int(v) for k, v in row.items()}
    except psycopg2.Error:
        conn.rollback()
    return dict(DEFAULT_SAMPLING)
```

- [ ] **Step 3: Add the per-row override in `claim_batch` + `process_file`**

In `scripts/force_orchestrator.py:186-211` (`claim_batch`), add `a.pulses_per_rev` to the `RETURNING` clause:

```python
def claim_batch(conn, args, limit: int):
    """Atomically move up to `limit` pending rows to 'processing'; return them."""
    scope, sparams = _scope_exists(args, "a")
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            WITH picked AS (
                SELECT a.id
                FROM machining_force_analysis a
                WHERE a.status = 'pending' {scope}
                ORDER BY a.created_at
                LIMIT {int(limit)}
                FOR UPDATE SKIP LOCKED
            )
            UPDATE machining_force_analysis a
               SET status='processing', updated_at=now()
              FROM picked
             WHERE a.id = picked.id
         RETURNING a.id, a.operation_id, a.directus_files_id,
                   a.frm_fx AS old_fx, a.frm_fy AS old_fy, a.frm_fz AS old_fz,
                   a.live_cache_file AS old_cache, a.live_render_points, a.pulses_per_rev,
                   (SELECT metadata->>'archive_path' FROM directus_files WHERE id = a.directus_files_id) AS archive_path,
                   (SELECT metadata->>'fingerprint'  FROM directus_files WHERE id = a.directus_files_id) AS fingerprint
        """,
            sparams,
        )
        rows = cur.fetchall()
    conn.commit()
    return rows
```

In `scripts/force_orchestrator.py:253-282` (`process_file`), add the override alongside the existing `live_render_points` one:

```python
def process_file(row, exe: str, timeout: int, matlab_opts: dict) -> dict:
    """Run MATLAB for one file. Returns a result dict (no DB / network here).
    A row's live_render_points (a Tier-2 "Process at N points" request from the
    dashboard) overrides live_cache_points just for that file — so the browser can
    ask for a denser (down to 1:1) point cloud without changing the global setting.
    A row's pulses_per_rev (set directly on the item, outside Live mode) likewise
    overrides the global tacho pulses-per-rev just for that file."""
    workroot = os.environ.get("FORCE_WORKDIR")
    outdir = tempfile.mkdtemp(prefix="force_", dir=workroot)
    res = {
        "id": row["id"],
        "outdir": outdir,
        "status": "error",
        "message": "",
        "summary": {},
    }
    try:
        req = row.get("live_render_points")
        if req and int(req) > 0:
            matlab_opts = {**matlab_opts, "live_cache_points": int(req)}
        ppr = row.get("pulses_per_rev")
        if ppr and int(ppr) > 0:
            matlab_opts = {**matlab_opts, "pulses_per_rev": int(ppr)}
        unc = unc_for(row["archive_path"])
        ok, err = run_matlab(exe, unc, outdir, timeout, matlab_opts)
        if not ok:
            res["message"] = err
            return res
        summ_path = Path(outdir) / "summary.json"
        if not summ_path.exists():
            res["message"] = "no summary.json produced"
            return res
        summary = json.loads(summ_path.read_text(encoding="utf-8"))
        res["summary"] = summary
        if summary.get("status") != "done":
            res["message"] = summary.get(
                "message", "processing reported non-done status"
            )
            return res
        res["status"] = "done"
    except Exception as e:  # noqa: BLE001 - want the message recorded
        res["message"] = f"{type(e).__name__}: {e}"
    return res
```

- [ ] **Step 4: Verify with a syntax/import check**

Run: `py -m py_compile scripts/force_orchestrator.py`
Expected: exits 0, no output.

Run: `py -c "import ast; ast.parse(open('scripts/force_orchestrator.py', encoding='utf-8').read())"`
Expected: no exception.

If `DATABASE_URL` and a running dev Postgres+Directus are available, additionally run a dry pass:
`DATABASE_URL=<dsn> py scripts/force_orchestrator.py --discover --dry-run -v`
Expected: logs the queue counts without error, confirming `load_sampling_opts` reads the new column without an SQL error.

- [ ] **Step 5: Commit**

```bash
git add scripts/force_orchestrator.py
git commit -m "$(cat <<'EOF'
feat(force): thread pulses_per_rev through the orchestrator

Global default from force_crawler_state, per-row override the same way
live_render_points already overrides live_cache_points, and the resolved
value written back via the existing SUMMARY_COLS/ingest mechanism.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `d1-force-crawler` admin UI — global default field

**Files:**
- Modify: `core/extensions/d1-force-crawler/src/Crawler.vue:16-117` (draft/state/save), `core/extensions/d1-force-crawler/src/Crawler.vue:255-262` (template)

**Interfaces:**
- Consumes: `force_crawler_state.pulses_per_rev` (Task 1).
- Produces: nothing new consumed elsewhere — this is a leaf UI.

- [ ] **Step 1: Add the field to the draft default and `loadState`**

In `core/extensions/d1-force-crawler/src/Crawler.vue:16-20`:

```javascript
const draft = ref({
	workers: 2, throttle_seconds: 5, file_like: '', op_code_like: '',
	series_points: 3000, fft_points: 3000, frm_downsample_step: 5, frm_dpi: 300,
	live_cache_points: 250000, pulses_per_rev: 1,
});
```

In `core/extensions/d1-force-crawler/src/Crawler.vue:28-39` (`loadState`):

```javascript
	if (!dirty.value && state.value) {
		draft.value = {
			workers: state.value.workers,
			throttle_seconds: Number(state.value.throttle_seconds),
			file_like: state.value.file_like || '',
			op_code_like: state.value.op_code_like || '',
			series_points: state.value.series_points,
			fft_points: state.value.fft_points,
			frm_downsample_step: state.value.frm_downsample_step,
			frm_dpi: state.value.frm_dpi,
			live_cache_points: state.value.live_cache_points,
			pulses_per_rev: state.value.pulses_per_rev,
		};
	}
```

- [ ] **Step 2: Add the field to `saveSettings`**

In `core/extensions/d1-force-crawler/src/Crawler.vue:98-117`:

```javascript
async function saveSettings() {
	saving.value = true;
	try {
		await api.patch('/items/force_crawler_state', {
			workers: Number(draft.value.workers) || 1,
			throttle_seconds: Number(draft.value.throttle_seconds) || 0,
			file_like: draft.value.file_like || null,
			op_code_like: draft.value.op_code_like || null,
			series_points: Math.max(100, Number(draft.value.series_points) || 3000),
			fft_points: Math.max(100, Number(draft.value.fft_points) || 3000),
			frm_downsample_step: Math.max(1, Number(draft.value.frm_downsample_step) || 5),
			frm_dpi: Math.max(72, Number(draft.value.frm_dpi) || 300),
			live_cache_points: Math.max(1000, Number(draft.value.live_cache_points) || 250000),
			pulses_per_rev: Math.max(1, Number(draft.value.pulses_per_rev) || 1),
		});
		dirty.value = false;
		await loadState();
	} finally {
		saving.value = false;
	}
}
```

- [ ] **Step 3: Add the input to the template**

In `core/extensions/d1-force-crawler/src/Crawler.vue:255-262`:

```html
						<div class="form-sep">Sampling (applies to files processed after saving)</div>
						<div class="form">
							<label>Series points<input v-model.number="draft.series_points" type="number" min="100" step="100" @input="dirty = true" /></label>
							<label>FFT points<input v-model.number="draft.fft_points" type="number" min="100" step="100" @input="dirty = true" /></label>
							<label>FRM downsample (every Nth pt)<input v-model.number="draft.frm_downsample_step" type="number" min="1" step="1" @input="dirty = true" /></label>
							<label>FRM DPI<input v-model.number="draft.frm_dpi" type="number" min="72" step="6" @input="dirty = true" /></label>
						<label>Live cache points<input v-model.number="draft.live_cache_points" type="number" min="1000" step="1000" @input="dirty = true" /></label>
						<label>Pulses per rev<input v-model.number="draft.pulses_per_rev" type="number" min="1" step="1" @input="dirty = true" /></label>
						</div>
```

- [ ] **Step 4: Build to check for TypeScript/Vue errors**

Run: `cd core/extensions/d1-force-crawler && npm run build`
Expected: exits 0, `dist/index.js` regenerated with no TS errors.

- [ ] **Step 5: Add a Playwright assertion for the new field**

In `tests/ui/specs/12-force-crawler.spec.ts`, extend the existing settings-form test:

```typescript
	// Settings form is present and editable.
	const workers = page.locator('.form label', { hasText: 'Workers' }).locator('input');
	await expect(workers).toBeVisible();
	const original = await workers.inputValue();
	await workers.fill('3');
	await expect(page.locator('.savebtn')).toBeEnabled();
	// Restore, so this test doesn't mutate the live daemon's worker count.
	await workers.fill(original || '2');

	// Pulses-per-rev default is present in the sampling settings group.
	const ppr = page.locator('.form label', { hasText: 'Pulses per rev' }).locator('input');
	await expect(ppr).toBeVisible();
	await expect(ppr).toHaveValue(/^\d+$/);
```

- [ ] **Step 6: Run the Playwright test**

Run: `cd tests/ui && npx playwright test 12-force-crawler`
Expected: `1 passed`. (Skip if no dev Directus instance is reachable in this environment — note that explicitly in the task result.)

- [ ] **Step 7: Commit**

```bash
git add core/extensions/d1-force-crawler/src/Crawler.vue tests/ui/specs/12-force-crawler.spec.ts
git commit -m "$(cat <<'EOF'
feat(force-crawler): expose pulses-per-rev global default

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `liveCloud.ts` + `FrmCloud.vue` — client-side PPR divisor

**Files:**
- Modify: `core/extensions/d1-force-dashboard/src/liveCloud.ts:15-32` (types), `core/extensions/d1-force-dashboard/src/liveCloud.ts:51-77` (`buildCloud`)
- Modify: `core/extensions/d1-force-dashboard/src/FrmCloud.vue:16-32` (props), `core/extensions/d1-force-dashboard/src/FrmCloud.vue:126-132` (`buildCloud` call), `core/extensions/d1-force-dashboard/src/FrmCloud.vue:166-168` (watch array)

**Interfaces:**
- Consumes: nothing new from other tasks (pure client-side).
- Produces: `CloudParams.ppr: number` and `FrmCloud`'s new `ppr` prop, consumed by Task 6's `ForceDashboard.vue` (`:ppr="editPpr"`).

- [ ] **Step 1: Add `ppr` to `CloudParams`**

In `core/extensions/d1-force-dashboard/src/liveCloud.ts:18-32`:

```typescript
export interface CloudParams {
	axis: Axis;
	feed: number;          // mm/rev
	diam: number;          // mm
	speedMode: SpeedMode;
	rpm: number;           // constant-RPM value
	vc: number;            // constant-Vc value (m/min)
	timeScale: number;     // Rate override: elapsed-time scale for rpm/vc models (1 = cache Fs)
	ppr: number;           // pulses per rev — divides the cached (raw, PPR=1) revs_cum in 'measured' mode
	cropStartSec: number;
	cropEndSec: number;
	stride: number;        // client-side thinning (render every Nth point)
	gridding: boolean;     // bin into a grid (mean colour per cell) vs raw scatter
	gridN: number;         // grid resolution per axis when gridding
	colormap: (x: number) => [number, number, number];
}
```

Also update the module-level doc comment at the top of the file (`core/extensions/d1-force-dashboard/src/liveCloud.ts:6-12`) to mention PPR:

```typescript
// Geometry (mirrors scripts/matlab/process_force.m): with r = revolutions elapsed
// since the crop-start,  theta = 2*PI*r,  rho = Diam/2 - Feed*r,  x/y = pol2cart.
// Three speed models drive r:
//   measured — cached revs_cum (integrated from the real tacho at full res, at
//              PulsesPerRev=1) divided by the caller's ppr for the real rate
//   rpm      — constant spindle speed:      r = (RPM/60)*(t - t_cs)
//   vc       — constant surface speed Vc:   rho(t) = sqrt(rho0^2 - 2K*(t-t_cs)),
//              K = Feed*Vc*1000/(pi*120) [mm^2/s]; r = (rho0 - rho)/Feed
```

- [ ] **Step 2: Divide by `ppr` in the measured branch of `buildCloud`**

In `core/extensions/d1-force-dashboard/src/liveCloud.ts:51-77`:

```typescript
export function buildCloud(c: Cache, p: CloudParams): Cloud | null {
	const t = c.t, revs = c.revs;
	const cs = idxOfTime(t, p.cropStartSec);
	const ceTime = p.cropEndSec;
	const F = p.feed, D = p.diam, rho0 = D / 2;
	const revsCs = revs[cs], tCs = t[cs];
	const revPerSec = p.rpm / 60;
	const ts = p.timeScale > 0 ? p.timeScale : 1;  // Rate override time scaling (rpm/vc only)
	const ppr = p.ppr > 0 ? p.ppr : 1;
	const K = F * p.vc * 1000 / (Math.PI * 120);   // constant-Vc coefficient
	const stride = Math.max(1, Math.round(p.stride) || 1);
	const Faxis = c[p.axis];

	const xs: number[] = [], ys: number[] = [], fv: number[] = [];
	let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
	for (let i = cs; i < c.N; i += stride) {
		if (t[i] > ceTime) break;
		let r: number, rho: number;
		if (p.speedMode === 'vc') {
			const under = rho0 * rho0 - 2 * K * (t[i] - tCs) * ts;
			if (under < 0) break;
			rho = Math.sqrt(under);
			r = (rho0 - rho) / F;
		} else {
			r = p.speedMode === 'rpm' ? revPerSec * (t[i] - tCs) * ts : (revs[i] - revsCs) / ppr;
			rho = rho0 - F * r;
			if (rho < 0) break;
		}
		const theta = 2 * Math.PI * r;
		const x = rho * Math.cos(theta), y = rho * Math.sin(theta);
		xs.push(x); ys.push(y); fv.push(Faxis[i]);
		if (x < minX) minX = x; if (x > maxX) maxX = x;
		if (y < minY) minY = y; if (y > maxY) maxY = y;
	}
	if (!fv.length) return null;
```

(Only the `measured`-mode branch — the `else` on the ternary — changed, from `(revs[i] - revsCs)` to `(revs[i] - revsCs) / ppr`; a `ppr` local is added next to the existing `ts` local.)

- [ ] **Step 3: Add the `ppr` prop to `FrmCloud.vue`**

In `core/extensions/d1-force-dashboard/src/FrmCloud.vue:16-32`:

```typescript
const props = defineProps<{
	cacheFileId: string;
	axis: Axis;
	feed: number;
	diam: number;
	speedMode: SpeedMode;
	rpm: number;
	vc: number;
	timeScale: number;
	ppr: number;
	cropStartSec: number;
	cropEndSec: number;
	stride: number;
	gridding: boolean;
	gridN: number;
	pointSize: number;
	colormap: string;
}>();
```

- [ ] **Step 4: Pass `ppr` into `buildCloud` and the redraw watcher**

In `core/extensions/d1-force-dashboard/src/FrmCloud.vue:126-132`:

```typescript
	const cloud = buildCloud(cache.value, {
		axis: props.axis, feed: props.feed, diam: props.diam,
		speedMode: props.speedMode, rpm: props.rpm, vc: props.vc, timeScale: props.timeScale,
		ppr: props.ppr,
		cropStartSec: props.cropStartSec, cropEndSec: props.cropEndSec,
		stride: props.stride, gridding: props.gridding, gridN: props.gridN,
		colormap: COLORMAPS[props.colormap] || COLORMAPS.viridis,
	});
```

In `core/extensions/d1-force-dashboard/src/FrmCloud.vue:166-168`:

```typescript
watch(() => [props.axis, props.feed, props.diam, props.speedMode, props.rpm, props.vc, props.timeScale, props.ppr,
	props.cropStartSec, props.cropEndSec, props.stride, props.gridding, props.gridN,
	props.pointSize, props.colormap], scheduleDraw);
```

- [ ] **Step 5: Build to check for TypeScript errors**

Run: `cd core/extensions/d1-force-dashboard && npm run build`
Expected: fails at this point with a TS error like `Property 'ppr' is missing in type ... but required in type 'CloudParams'` for the call site in `ForceDashboard.vue` (not yet updated) — that's expected here; Task 6 fixes it. Confirm the error is specifically about the missing `ppr`/prop, not something else.

- [ ] **Step 6: Commit**

```bash
git add core/extensions/d1-force-dashboard/src/liveCloud.ts core/extensions/d1-force-dashboard/src/FrmCloud.vue
git commit -m "$(cat <<'EOF'
feat(force-dashboard): add client-side pulses-per-rev divisor

buildCloud's measured-mode branch now divides the cached (raw, PPR=1)
revs_cum by an editable ppr, mirroring how Feed/Diameter are already
instant client-side parameters. FrmCloud plumbs the new prop through.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: `ForceDashboard.vue` — Live mode "Pulses/rev" control

**Files:**
- Modify: `core/extensions/d1-force-dashboard/src/ForceDashboard.vue:57-63` (editable refs), `core/extensions/d1-force-dashboard/src/ForceDashboard.vue:334-350` (`loadDetail` fields), `core/extensions/d1-force-dashboard/src/ForceDashboard.vue:498-508` (`resetLive`), `core/extensions/d1-force-dashboard/src/ForceDashboard.vue:684-698` (template edit-grid), `core/extensions/d1-force-dashboard/src/ForceDashboard.vue:782-787` (`FrmCloud` binding)

**Interfaces:**
- Consumes: `CloudParams.ppr` / `FrmCloud`'s `ppr` prop (Task 5); `machining_force_analysis.pulses_per_rev` (Task 1).
- Produces: nothing new consumed elsewhere.

- [ ] **Step 1: Add the `editPpr` ref**

In `core/extensions/d1-force-dashboard/src/ForceDashboard.vue:57-63`:

```typescript
const editFeed = ref(0.1);
const editDiam = ref(80);
const speedMode = ref<SpeedMode>('measured');
const editRpm = ref(1000);
const editVc = ref(100);
const editRate = ref(25600);
const editPpr = ref(1);
let cacheFs = 25600;                              // the cache's own Fs, for the Rate time-scale
```

- [ ] **Step 2: Fetch `pulses_per_rev` in `loadDetail` and seed `editPpr`**

In `core/extensions/d1-force-dashboard/src/ForceDashboard.vue:334-351`, add the field to the `fields` list and seed `editPpr` once the row loads:

```typescript
		const res = await api.get(`/items/machining_force_analysis/${row.id}`, {
			params: {
				fields: ['*',
					'operation_id.operation_id', 'operation_id.pass_code', 'operation_id.operation_date',
					'operation_id.operation_sequence', 'operation_id.machining_operation_subtype',
					'operation_id.process_category', 'operation_id.operator_name',
					'operation_id.machining_new_edge', 'operation_id.machining_coolant_used', 'operation_id.outcome_notes',
					'operation_id.equipment_id.equipment_name', 'operation_id.method_id.method_name',
					'operation_id.sample_id.sample_id', 'operation_id.sample_id.sample_code', 'operation_id.sample_id.nickname',
					'operation_id.sample_id.form', 'operation_id.sample_id.manufactured_date',
					'operation_id.sample_id.owner_person_id.full_name',
					'operation_id.sample_id.material_id.common_name',
					'directus_files_id.filesize', 'live_cache_file', 'live_render_points', 'pulses_per_rev'],
			},
		});
		detail.value = res.data.data;
		editPpr.value = Number(detail.value?.pulses_per_rev) || 1;
		await loadFrm();
```

- [ ] **Step 3: Reset `editPpr` in `resetLive`**

In `core/extensions/d1-force-dashboard/src/ForceDashboard.vue:498-508`:

```typescript
function resetLive() {
	const d = detail.value;
	if (cropWindow.value) { cropStartSec.value = cropWindow.value.start; cropEndSec.value = cropWindow.value.end; }
	if (d) {
		editFeed.value = Number(d.feed) || editFeed.value;
		editDiam.value = Number(d.cut_diameter) || editDiam.value;
		editRate.value = Number(d.sample_rate) || editRate.value;
		editPpr.value = Number(d.pulses_per_rev) || 1;
	}
	speedMode.value = 'measured';
	plotStride.value = 1; gridding.value = false; pointSize.value = 1.4; colormap.value = 'viridis';
}
```

- [ ] **Step 4: Add the template input**

In `core/extensions/d1-force-dashboard/src/ForceDashboard.vue:683-698`:

```html
								<div class="stat-sep">Plot metadata <button class="linkbtn" @click="resetLive">Reset</button></div>
								<div class="edit-grid">
									<label>Feed <span class="u">mm/rev</span><input v-model.number="editFeed" type="number" step="0.01" min="0" /></label>
									<label>Diameter <span class="u">mm</span><input v-model.number="editDiam" type="number" step="1" min="0" /></label>
									<label>Pulses/rev<input v-model.number="editPpr" type="number" step="1" min="1" /></label>
									<label class="wide">Spindle speed
										<div class="speed-row">
											<select v-model="speedMode">
												<option value="measured">Measured (tacho)</option>
												<option value="rpm">Constant RPM</option>
												<option value="vc">Constant Vc</option>
											</select>
											<input v-if="speedMode === 'rpm'" v-model.number="editRpm" type="number" step="10" min="1" title="RPM" />
											<input v-if="speedMode === 'vc'" v-model.number="editVc" type="number" step="1" min="1" title="Vc (m/min)" />
										</div>
									</label>
									<label>Rate <span class="u">Hz</span><input v-model.number="editRate" type="number" step="100" min="1" /></label>
								</div>
```

- [ ] **Step 5: Bind the new prop on `FrmCloud`**

In `core/extensions/d1-force-dashboard/src/ForceDashboard.vue:782-787`:

```html
								<FrmCloud v-else-if="liveOn" :cache-file-id="detail.live_cache_file"
									:axis="axis" :feed="editFeed" :diam="editDiam" :speed-mode="speedMode"
									:rpm="editRpm" :vc="editVc" :time-scale="timeScale" :ppr="editPpr"
									:crop-start-sec="cropStartSec" :crop-end-sec="cropEndSec"
									:stride="plotStride" :gridding="gridding" :grid-n="gridN"
									:point-size="pointSize" :colormap="colormap" @loaded="onCloudLoaded" />
```

- [ ] **Step 6: Build to confirm the TS error from Task 5 is now resolved**

Run: `cd core/extensions/d1-force-dashboard && npm run build`
Expected: exits 0, `dist/index.js` regenerated, no TS errors.

- [ ] **Step 7: Add a Playwright assertion for Live mode's Pulses/rev control**

In `tests/ui/specs/11-force-dashboard.spec.ts`, add a new test after the existing two:

```typescript
test('force dashboard: Live mode exposes an editable Pulses/rev control', async ({ page }) => {
	await page.goto('/admin/d1-force-dashboard', { waitUntil: 'domcontentloaded' });

	const ops = page.locator('.panel-ops .rowcard');
	await expect(ops.first()).toBeVisible({ timeout: 20_000 });
	await ops.first().click();
	await expect(page.locator('.card.info .stat').first()).toBeVisible({ timeout: 20_000 });

	const liveBtn = page.locator('.toggle .tbtn', { hasText: 'Live' });
	test.skip(await liveBtn.isDisabled(), 'this operation has no live cache to enable Live mode');

	await liveBtn.click();
	await expect(liveBtn).toHaveClass(/on/);

	const ppr = page.locator('.edit-grid label', { hasText: 'Pulses/rev' }).locator('input');
	await expect(ppr).toBeVisible({ timeout: 20_000 });
	const original = await ppr.inputValue();
	expect(Number(original)).toBeGreaterThanOrEqual(1);

	// Editing it re-renders the FRM cloud without erroring (point count stays > 0).
	await ppr.fill('2');
	await page.waitForTimeout(400);
	await expect(page.locator('.fc-count')).toBeVisible({ timeout: 20_000 });

	// Reset restores the original value.
	await page.locator('.linkbtn', { hasText: 'Reset' }).click();
	await expect(ppr).toHaveValue(original);
});
```

- [ ] **Step 8: Run the Playwright tests**

Run: `cd tests/ui && npx playwright test 11-force-dashboard`
Expected: `3 passed` (or the new test explicitly skipped if no operation in the seeded test data has a `live_cache_file`). Note in the task result which outcome occurred.

- [ ] **Step 9: Commit**

```bash
git add core/extensions/d1-force-dashboard/src/ForceDashboard.vue tests/ui/specs/11-force-dashboard.spec.ts
git commit -m "$(cat <<'EOF'
feat(force-dashboard): editable Pulses/rev in Live mode

Seeded from the row's stored pulses_per_rev (default 1), instant
client-side divisor on the FRM cloud, preview-only until a real value is
set on the item and the row is reprocessed — same contract as Feed/Diameter.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage:** FitType hardcode (Task 2 Step 2) ✓; global default schema (Task 1) ✓; per-op schema (Task 1) ✓; canonical MATLAB processing incl. the raw/real rpm split (Task 2) ✓; orchestrator threading incl. summary round-trip (Task 3) ✓; crawler admin UI (Task 4) ✓; Live mode instant client divisor (Task 5+6) ✓; Live mode preview-only contract, no Process-button persistence (Task 6 — no PATCH change made to `processFullRes`, matching the corrected spec) ✓; RPM/Force envelope strips left untouched (no `series` changes) ✓; constant-RPM/Vc models unaffected by PPR (Task 5 Step 2 — `ppr` only divides the `else` measured branch) ✓.
- **Type consistency:** `CloudParams.ppr` (Task 5) → `FrmCloud` prop `ppr` (Task 5) → `ForceDashboard.vue`'s `editPpr` bound as `:ppr="editPpr"` (Task 6) — names match throughout. `machining_force_analysis.pulses_per_rev` (Task 1) → `SUMMARY_COLS` entry `"pulses_per_rev"` (Task 3) → MATLAB's `summary.pulses_per_rev` (Task 2) — same key end to end, no aliasing needed.
- **No placeholders:** every step above has complete, copy-pasteable code.
