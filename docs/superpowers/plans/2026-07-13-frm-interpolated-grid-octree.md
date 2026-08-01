# FRM interpolated-grid octree Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a server-generated, GPU-accelerated interpolated-grid octree variant to the FRM force dashboard — a dense, anti-aliased, filled map that fills the sparse spiral at deep zoom — with a per-op fidelity estimate and crawler settings, reusing the existing octree pipeline.

**Architecture:** MATLAB `process_force.m` gains a `grid_out` early-return branch that interpolates the raw spiral onto an N×N grid (`splat` GPU/CPU or `natural`), computes a hold-out-arms fidelity number, and emits a `D1GR` binary. `force_orchestrator.py` gains a grid-octree handler (near-clone of `process_octree_row`) that turns the `D1GR` binary into a Potree octree under `infra/octrees/grid/<op_id>/` and records DB fields. The dashboard's existing "Grid binning" checkbox becomes a mode-aware "Gridded" toggle that, in Full-res mode, loads the grid octree (built on demand) into a fill-rendering `FrmOctree`, with a fidelity chip. New crawler settings tune density/method/octree LOD.

**Tech Stack:** MATLAB R2025a (Parallel Computing Toolbox `gpuArray` optional), Python 3 (psycopg2, laspy, numpy, PotreeConverter 2.1.1), Directus extensions (Vue 3 `<script setup>` + TypeScript, three.js + potree-core), Postgres, dbmate migrations.

## Global Constraints

- **Grid density:** default `2048`, hard cap `8192`. Clamp everywhere it is read or written.
- **Grid method:** `splat` | `natural`, default `splat`.
- **CV params:** `cv_fraction = 0.10`, `cv_arm_step = 10` (hold out every 10th spiral revolution).
- **Fidelity:** computed on resultant magnitude `|F| = sqrt(Fx²+Fy²+Fz²)`; `grid_fidelity = clamp(1 − nRMSE, 0, 1)`, reported as a %. Chip is green at ≥ **95%**, else amber. `n/a` when fewer than ~3 arms.
- **`octree_min_node_px`** default `1`; **`octree_budget_cap`** default `25_000_000`; **`octree_threshold`** seeded from current `live_cache_points`.
- **Force is 12-bit at source** → int16-scaled LAS storage is lossless.
- **D1GR binary** (little-endian): `magic u32 = 0x44314752 ('D1GR')`, `N u32`, `fidelity f32`, `arm_ratio f32`, `cell_mm f32`, then `x[N] y[N] Fx[N] Fy[N] Fz[N]` float32. (Adds `cell_mm` to the spec's header so the client can size fill points exactly.)
- **Grid octree served path:** `OCTREE_DIR/grid/<op_id>/`, i.e. Caddy `/octrees/grid/<op_id>/` (already `Cache-Control: no-cache`).
- Extensions build with `directus-extension build`; **restart `d1-database-directus-1`** after a rebuild. Migrations run with dbmate. The force daemon (`py scripts/force_orchestrator.py --daemon`) is session-scoped and started by the user. Never commit `.env`, `.crt`, `docker-compose.override.yml`, `FAST Data/`, `.claude/`. Commit only when a step says to.

---

## File Structure

- **`db/migrations/20260713000094_frm_grid_octree.sql`** (create) — `machining_force_analysis` grid columns + `force_crawler_state` settings + Directus field registration.
- **`scripts/matlab/process_force.m`** (modify) — new `grid_out` branch (~after line 223).
- **`scripts/matlab/frm_grid_interp.m`** (create) — public `frm_grid_interp`; local `grid_natural`. Interpolates spiral → grid.
- **`scripts/matlab/frm_grid_splat.m`** (create) — public `frm_grid_splat` (shared by interp + fidelity's splat predict); GPU-accelerated blur.
- **`scripts/matlab/frm_grid_fidelity.m`** (create) — public `frm_grid_fidelity`; local `compute_arm_ratio`, `predict_natural`, `predict_splat`.

(MATLAB makes only the *first* function in a file externally callable; each public helper therefore needs its own file. Private sub-helpers stay local to their file.)
- **`scripts/matlab/test_grid_out.m`** (create) — MATLAB test harness (asserts, errors on failure) run via `matlab -batch`.
- **`scripts/force_orchestrator.py`** (modify) — `_read_grid_bin`, `claim_grid`, `process_grid_row`, `handle_grids`, `load_grid_opts`; wire into `run_queue` + `run_daemon`.
- **`scripts/test_grid_bin.py`** (create) — pytest for the `D1GR` reader + int16 LAS round-trip.
- **`core/extensions/d1-force-dashboard/src/FrmOctree.vue`** (modify) — `fill` + `cellSize` + `minNodePx` + `budgetCap` props → world-space fill point sizing.
- **`core/extensions/d1-force-dashboard/src/ForceDashboard.vue`** (modify) — fetch grid fields, grid state/computed, `buildGridOctree`, "Gridded" toggle wiring, fidelity chip, octree tuning pass-through.
- **`core/extensions/d1-force-crawler/src/Crawler.vue`** (modify) — "Gridding & octree" settings block.
- **`tests/ui/specs/11-force-dashboard.spec.ts`** (modify) — Playwright: Gridded toggle + fill + fidelity chip + settings round-trip.

---

## Task 1: DB migration — schema + settings + Directus fields

**Files:**
- Create: `db/migrations/20260713000094_frm_grid_octree.sql`

**Interfaces:**
- Produces (columns other tasks read/write):
  - `machining_force_analysis`: `grid_octree_status text`, `grid_octree_path text`, `grid_octree_points bigint`, `grid_octree_error text`, `grid_octree_requested_at timestamptz`, `grid_fidelity real`, `grid_arm_ratio real`, `grid_cell_mm real`.
  - `force_crawler_state`: `grid_density int NOT NULL DEFAULT 2048`, `grid_method text NOT NULL DEFAULT 'splat'`, `octree_threshold int`, `octree_min_node_px real NOT NULL DEFAULT 1`, `octree_budget_cap int NOT NULL DEFAULT 25000000`.

- [ ] **Step 1: Write the migration**

Create `db/migrations/20260713000094_frm_grid_octree.sql`:

```sql
-- migrate:up
-- FRM interpolated-grid octree: a second octree variant per op, built from the spiral
-- interpolated onto a fine N×N grid (MATLAB grid_out -> D1GR binary -> LAS -> PotreeConverter),
-- served under /octrees/grid/<op_id>/. Mirrors the raw octree_* columns and adds the fidelity
-- estimate + cell size. force_crawler_state gains the gridding + octree LOD tuning knobs.

ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS grid_octree_status       text,        -- null | pending | processing | done | error
    ADD COLUMN IF NOT EXISTS grid_octree_path         text,        -- served subdir under /octrees/grid/
    ADD COLUMN IF NOT EXISTS grid_octree_points       bigint,      -- kept grid cells (points in the octree)
    ADD COLUMN IF NOT EXISTS grid_octree_error        text,
    ADD COLUMN IF NOT EXISTS grid_octree_requested_at timestamptz,
    ADD COLUMN IF NOT EXISTS grid_fidelity            real,        -- 0..1 hold-out-arms cross-validation
    ADD COLUMN IF NOT EXISTS grid_arm_ratio           real,        -- median arm spacing / cell size
    ADD COLUMN IF NOT EXISTS grid_cell_mm             real;        -- grid cell size (mm), for fill sizing

-- octree_threshold decouples the dashboard's auto-route from live_cache_points; seed it from
-- the current value so behaviour is unchanged until an admin edits it.
ALTER TABLE force_crawler_state
    ADD COLUMN IF NOT EXISTS grid_density        integer NOT NULL DEFAULT 2048,
    ADD COLUMN IF NOT EXISTS grid_method         text    NOT NULL DEFAULT 'splat',
    ADD COLUMN IF NOT EXISTS octree_threshold    integer,
    ADD COLUMN IF NOT EXISTS octree_min_node_px  real    NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS octree_budget_cap   integer NOT NULL DEFAULT 25000000;

UPDATE force_crawler_state
   SET octree_threshold = live_cache_points
 WHERE octree_threshold IS NULL;

COMMENT ON COLUMN force_crawler_state.grid_density       IS 'Interpolated-grid resolution N (N×N cells); capped at 8192.';
COMMENT ON COLUMN force_crawler_state.grid_method        IS 'Grid interpolation: splat (Gaussian, GPU) or natural (Delaunay).';
COMMENT ON COLUMN force_crawler_state.octree_threshold   IS 'Auto-route to the octree view above this many points.';
COMMENT ON COLUMN force_crawler_state.octree_min_node_px IS 'Potree LOD: min projected node size (px) before culling.';
COMMENT ON COLUMN force_crawler_state.octree_budget_cap  IS 'Potree point-budget hard cap (GPU safety).';

INSERT INTO directus_fields (collection, field, interface, display, options, width, sort, readonly, hidden)
SELECT collection, field, interface, display, options::json, width, sort, readonly, hidden
FROM (VALUES
    ('force_crawler_state', 'grid_density',       'input',         'raw', NULL, 'half', 10, false, false),
    ('force_crawler_state', 'grid_method',        'select-dropdown','raw',
        '{"choices":[{"text":"splat","value":"splat"},{"text":"natural","value":"natural"}]}', 'half', 11, false, false),
    ('force_crawler_state', 'octree_threshold',   'input',         'raw', NULL, 'half', 12, false, false),
    ('force_crawler_state', 'octree_min_node_px', 'input',         'raw', NULL, 'half', 13, false, false),
    ('force_crawler_state', 'octree_budget_cap',  'input',         'raw', NULL, 'half', 14, false, false)
) v(collection, field, interface, display, options, width, sort, readonly, hidden)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- migrate:down
DELETE FROM directus_fields WHERE collection = 'force_crawler_state'
    AND field IN ('grid_density', 'grid_method', 'octree_threshold', 'octree_min_node_px', 'octree_budget_cap');
ALTER TABLE force_crawler_state
    DROP COLUMN IF EXISTS grid_density,
    DROP COLUMN IF EXISTS grid_method,
    DROP COLUMN IF EXISTS octree_threshold,
    DROP COLUMN IF EXISTS octree_min_node_px,
    DROP COLUMN IF EXISTS octree_budget_cap;
ALTER TABLE machining_force_analysis
    DROP COLUMN IF EXISTS grid_octree_status,
    DROP COLUMN IF EXISTS grid_octree_path,
    DROP COLUMN IF EXISTS grid_octree_points,
    DROP COLUMN IF EXISTS grid_octree_error,
    DROP COLUMN IF EXISTS grid_octree_requested_at,
    DROP COLUMN IF EXISTS grid_fidelity,
    DROP COLUMN IF EXISTS grid_arm_ratio,
    DROP COLUMN IF EXISTS grid_cell_mm;
```

- [ ] **Step 2: Apply the migration**

Run: `docker compose exec -T directus npx dbmate up` (or the project's usual dbmate invocation — check `scripts/` / `docker-compose.yml` for how migrations are run; the DB service is Postgres and migrations live in `db/migrations`).
Expected: migration `20260713000094_frm_grid_octree` applied, no error.

- [ ] **Step 3: Verify the columns exist**

Run:
```bash
docker compose exec -T db psql -U d1 -d d1_database -c "\d force_crawler_state" | grep -E "grid_density|grid_method|octree_threshold|octree_min_node_px|octree_budget_cap"
docker compose exec -T db psql -U d1 -d d1_database -c "SELECT octree_threshold, live_cache_points FROM force_crawler_state;"
```
Expected: the five settings columns listed; `octree_threshold` equals `live_cache_points`.

- [ ] **Step 4: Commit**

```bash
git add db/migrations/20260713000094_frm_grid_octree.sql
git commit -m "feat(force): schema + settings for FRM interpolated-grid octree"
```

---

## Task 2: MATLAB gridding + fidelity helpers

Pure functions, unit-testable in isolation on synthetic data before wiring into `process_force.m`. Each public helper is its own file (MATLAB only exports the first function in a file).

**Files:**
- Create: `scripts/matlab/frm_grid_interp.m`, `scripts/matlab/frm_grid_splat.m`, `scripts/matlab/frm_grid_fidelity.m`
- Test: `scripts/matlab/test_grid_out.m` (fidelity/grid asserts added here in Step 1; extended in Task 3)

**Interfaces:**
- Produces:
  - `[gx, gy, gFx, gFy, gFz, cell] = frm_grid_interp(xx, yy, cFx, cFy, cFz, N, method)` — column vectors of kept in-support grid-cell centres and interpolated forces; `cell` = grid spacing (mm, scalar). `method` ∈ `{'splat','natural'}`.
  - `[fidelity, arm_ratio] = frm_grid_fidelity(xx, yy, theta_cum, cFx, cFy, cFz, N, method, cell, cv_arm_step)` — scalars; `fidelity = clamp(1 − nRMSE, 0, 1)` over `|F|`, `NaN` if uncomputable.
  - Internal helper `frm_grid_build(xx, yy, v, x0, y0, cell, N, sigma)` → `[G, W]` (value-sum grid ÷ implied weight); GPU-accelerated when available.

- [ ] **Step 1: Write the failing test harness**

Create `scripts/matlab/test_grid_out.m`:

```matlab
function test_grid_out()
% Standalone asserts for the grid interpolation + fidelity helpers. Run:
%   matlab -batch "addpath('scripts/matlab'); test_grid_out"
% Errors (non-zero exit) on any failed assertion; prints PASS lines otherwise.

rng(7);
% Synthetic spiral: rho shrinks, theta winds — same geometry as the FRM.
turns = 12; ppt = 400; nrev = turns*ppt;
th = linspace(0, turns*2*pi, nrev)';
rho = linspace(40, 2, nrev)';
[xx, yy] = pol2cart(mod(th,2*pi), rho);
% A smooth field so interpolation should reconstruct it well.
truef = @(x,y) 100 + 30*sin(x/6) + 20*cos(y/5);
cFx = truef(xx,yy); cFy = 0.5*cFx; cFz = 2*cFx;

for method = {'splat','natural'}
    m = method{1};
    [gx, gy, gFx, gFy, gFz, cell] = frm_grid_interp(xx, yy, cFx, cFy, cFz, 256, m);
    assert(~isempty(gx), '%s: empty grid', m);
    assert(isequal(size(gx), size(gFx)), '%s: length mismatch', m);
    assert(cell > 0, '%s: bad cell', m);
    assert(all(gx >= min(xx)-cell & gx <= max(xx)+cell), '%s: x out of bounds', m);
    % interpolated values must stay within the data range (no wild overshoot)
    assert(min(gFx) >= min(cFx)-1 && max(gFx) <= max(cFx)+1, '%s: Fx overshoot', m);

    [fid, ratio] = frm_grid_fidelity(xx, yy, th, cFx, cFy, cFz, 256, m, cell, 3);
    assert(fid >= 0 && fid <= 1, '%s: fidelity out of [0,1] (%g)', m, fid);
    assert(fid > 0.5, '%s: fidelity too low on smooth field (%g)', m, fid);
    assert(ratio > 0, '%s: arm_ratio not positive (%g)', m, ratio);
    fprintf('PASS %s: n=%d cell=%.3f fidelity=%.3f arm_ratio=%.3f\n', m, numel(gx), cell, fid, ratio);
end

% CPU/GPU splat agreement (only if a GPU is present)
if gpuDeviceCount > 0
    [~,~,a] = frm_grid_interp(xx, yy, cFx, cFy, cFz, 256, 'splat');   % GPU path taken internally
    fprintf('PASS gpu present; splat ran\n');
end
fprintf('ALL GRID TESTS PASSED\n');
end
```

- [ ] **Step 2: Run the harness to confirm it fails (functions absent)**

Run: `matlab -batch "addpath('scripts/matlab'); test_grid_out"`
Expected: FAIL — `Unrecognized function or variable 'frm_grid_interp'`.

- [ ] **Step 3a: Implement `frm_grid_splat.m`** (shared by interp + fidelity)

Create `scripts/matlab/frm_grid_splat.m`:

```matlab
function [gx, gy, gFx, gFy, gFz] = frm_grid_splat(xx, yy, cFx, cFy, cFz, x0, y0, cell, N)
% Gaussian splat via scatter-then-separable-blur. Scatter each point's value + a unit
% weight into its nearest cell (accumarray), then convolve both with a separable Gaussian
% (sigma ~0.7 cell). value = blur(sum)/blur(weight). Keep cells with weight above eps (a
% data-support mask). The conv is offloaded to the GPU when one is present. Returns kept
% cell centres + interpolated forces as column vectors.
ix = min(N, max(1, floor((xx - x0)/cell) + 1));
iy = min(N, max(1, floor((yy - y0)/cell) + 1));
lin = sub2ind([N N], iy, ix);
W  = accumarray(lin, 1,           [N*N 1]);
Sx = accumarray(lin, double(cFx), [N*N 1]);
Sy = accumarray(lin, double(cFy), [N*N 1]);
Sz = accumarray(lin, double(cFz), [N*N 1]);
W = reshape(W,[N N]); Sx = reshape(Sx,[N N]); Sy = reshape(Sy,[N N]); Sz = reshape(Sz,[N N]);

sigma = 0.7; r = ceil(3*sigma); k = exp(-((-r:r).^2)/(2*sigma^2)); k = k / sum(k);
useGpu = gpuDeviceCount > 0;
if useGpu
    W = gpuArray(W); Sx = gpuArray(Sx); Sy = gpuArray(Sy); Sz = gpuArray(Sz); k = gpuArray(k);
end
blur = @(A) conv2(k, k, A, 'same');
Wb = blur(W); Sxb = blur(Sx); Syb = blur(Sy); Szb = blur(Sz);
mask = Wb > 1e-6;
Vx = zeros(N,N,'like',Wb); Vy = Vx; Vz = Vx;
Vx(mask) = Sxb(mask)./Wb(mask);
Vy(mask) = Syb(mask)./Wb(mask);
Vz(mask) = Szb(mask)./Wb(mask);
if useGpu
    mask = gather(mask); Vx = gather(Vx); Vy = gather(Vy); Vz = gather(Vz);
end
[iyk, ixk] = find(mask);
gx = x0 + (ixk - 0.5) * cell;
gy = y0 + (iyk - 0.5) * cell;
idx = sub2ind([N N], iyk, ixk);
gFx = Vx(idx); gFy = Vy(idx); gFz = Vz(idx);
end
```

- [ ] **Step 3b: Implement `frm_grid_interp.m`**

Create `scripts/matlab/frm_grid_interp.m`:

```matlab
function [gx, gy, gFx, gFy, gFz, cell] = frm_grid_interp(xx, yy, cFx, cFy, cFz, N, method)
% Interpolate scattered spiral points (xx,yy) with per-axis values onto an equal-aspect
% N×N grid; return the kept (data-supported / in-hull) cell centres and interpolated
% forces as column vectors, plus the cell spacing. method: 'splat' | 'natural'.
N = min(8192, max(16, round(N)));
xmin = min(xx); xmax = max(xx); ymin = min(yy); ymax = max(yy);
span = max(xmax - xmin, ymax - ymin);
if ~(span > 0); error('frm_grid:degenerate', 'zero-span spiral'); end
cell = span / N;
cx = (xmin + xmax)/2; cy = (ymin + ymax)/2;      % centre the equal-aspect box
x0 = cx - span/2; y0 = cy - span/2;              % lower-left of the square grid
xc = x0 + (0.5:N-0.5)' * cell;                   % cell-centre coordinates
yc = y0 + (0.5:N-0.5)' * cell;

switch lower(method)
    case 'natural'
        [gx, gy, gFx, gFy, gFz] = grid_natural(xx, yy, cFx, cFy, cFz, xc, yc);
    otherwise   % 'splat'
        [gx, gy, gFx, gFy, gFz] = frm_grid_splat(xx, yy, cFx, cFy, cFz, x0, y0, cell, N);
end
end

function [gx, gy, gFx, gFy, gFz] = grid_natural(xx, yy, cFx, cFy, cFz, xc, yc)
% Delaunay natural-neighbour interpolation (matches the manual MATLAB workflow). Keep only
% grid nodes inside the convex hull ('none' extrapolation -> NaN outside).
[GX, GY] = meshgrid(xc, yc);
fx = scatteredInterpolant(xx, yy, double(cFx), 'natural', 'none');
fy = scatteredInterpolant(xx, yy, double(cFy), 'natural', 'none');
fz = scatteredInterpolant(xx, yy, double(cFz), 'natural', 'none');
Vx = fx(GX, GY); Vy = fy(GX, GY); Vz = fz(GX, GY);
mask = ~isnan(Vx);
gx = GX(mask); gy = GY(mask);
gFx = Vx(mask); gFy = Vy(mask); gFz = Vz(mask);
end
```

- [ ] **Step 3c: Implement `frm_grid_fidelity.m`**

Create `scripts/matlab/frm_grid_fidelity.m`:

```matlab
function [fidelity, arm_ratio] = frm_grid_fidelity(xx, yy, theta_cum, cFx, cFy, cFz, N, method, cell, cv_arm_step)
% Hold-out-arms cross-validation. Arms = revolution index floor(theta_cum/2pi). Hold out
% every cv_arm_step-th arm; interpolate from the rest; predict at the held-out points; score
% nRMSE + fidelity on |F| = sqrt(Fx^2+Fy^2+Fz^2). arm_ratio = median arm spacing / cell.
arm = floor(theta_cum(:) / (2*pi));
arm = arm - min(arm);
narm = max(arm) + 1;
% median radial spacing between successive arms at matched angle ~ median |d rho| per turn.
rho = hypot(xx, yy);
arm_ratio = compute_arm_ratio(rho, arm, narm, cell);
if narm < 3
    fidelity = NaN; return;      % too few arms to hold any out
end
test = mod(arm, max(2, round(cv_arm_step))) == 0;
train = ~test;
if nnz(test) < 8 || nnz(train) < 32
    fidelity = NaN; return;
end
switch lower(method)
    case 'natural'
        px = predict_natural(xx(train), yy(train), cFx(train), xx(test), yy(test));
        py = predict_natural(xx(train), yy(train), cFy(train), xx(test), yy(test));
        pz = predict_natural(xx(train), yy(train), cFz(train), xx(test), yy(test));
    otherwise
        [px, py, pz] = predict_splat(xx(train), yy(train), cFx(train), cFy(train), cFz(train), ...
                                     xx(test), yy(test), cell, N);
end
ok = ~isnan(px) & ~isnan(py) & ~isnan(pz);
if nnz(ok) < 8; fidelity = NaN; return; end
predMag = sqrt(px(ok).^2 + py(ok).^2 + pz(ok).^2);
trueMag = sqrt(cFx(test).^2 + cFy(test).^2 + cFz(test).^2); trueMag = trueMag(ok);
rmse = sqrt(mean((predMag - trueMag).^2));
p = prctile(trueMag, [1 99]); rng_ = p(2) - p(1); if ~(rng_ > 0); rng_ = max(trueMag) - min(trueMag); end
if ~(rng_ > 0); fidelity = NaN; return; end
nrmse = rmse / rng_;
fidelity = min(1, max(0, 1 - nrmse));
end

function r = compute_arm_ratio(rho, arm, narm, cell)
% Median radial gap between consecutive arms (proxy for spiral pitch) divided by cell.
med = zeros(narm,1);
for a = 0:narm-1
    v = rho(arm == a);
    if ~isempty(v); med(a+1) = median(v); end
end
med = med(med > 0);
if numel(med) < 2; r = NaN; return; end
r = median(abs(diff(sort(med, 'descend')))) / cell;
if ~(r > 0); r = NaN; end
end

function v = predict_natural(xt, yt, ft, xq, yq)
f = scatteredInterpolant(xt, yt, double(ft), 'natural', 'none');
v = f(xq, yq);
end

function [px, py, pz] = predict_splat(xt, yt, fxt, fyt, fzt, xq, yq, cell, N)
% Build a splat grid from the training arms, then bilinearly sample it at the query points.
xmin = min([xt; xq]); ymin = min([yt; yq]);
x0 = xmin - cell; y0 = ymin - cell;
[gx, gy, gFx, gFy, gFz] = frm_grid_splat(xt, yt, fxt, fyt, fzt, x0, y0, cell, N); %#ok<ASGLU>
% Reassemble sparse grids to full for interpolation (griddata over kept centres).
px = griddata(gx, gy, gFx, xq, yq, 'linear');
py = griddata(gx, gy, gFy, xq, yq, 'linear');
pz = griddata(gx, gy, gFz, xq, yq, 'linear');
end
```

- [ ] **Step 4: Run the harness to verify it passes**

Run: `matlab -batch "addpath('scripts/matlab'); test_grid_out"`
Expected: `PASS splat …`, `PASS natural …`, `ALL GRID TESTS PASSED`, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/matlab/frm_grid_interp.m scripts/matlab/frm_grid_splat.m scripts/matlab/frm_grid_fidelity.m scripts/matlab/test_grid_out.m
git commit -m "feat(force): MATLAB grid interpolation + hold-out-arms fidelity helpers"
```

---

## Task 3: MATLAB `grid_out` branch in `process_force.m`

Wire the helpers into a `grid_out` early-return branch that emits the `D1GR` binary, next to the existing `octree_out` branch.

**Files:**
- Modify: `scripts/matlab/process_force.m` (insert after the `octree_out` branch, line 223)
- Test: `scripts/matlab/test_grid_out.m` (extend)

**Interfaces:**
- Consumes: `frm_grid_interp`, `frm_grid_fidelity` (Task 2).
- Produces: when `opts.grid_out` (path) and `opts.grid` struct are set, writes a `D1GR` binary and returns early. `opts.grid = struct('n', 2048, 'method', 'splat', 'cv_arm_step', 10)`.

- [ ] **Step 1: Extend the test harness with a `D1GR` reader assert**

Append to `scripts/matlab/test_grid_out.m` (before the final `fprintf('ALL GRID TESTS PASSED\n')`):

```matlab
% ---- D1GR binary emit round-trip (build a tiny synthetic .mat, run process_force) ----
tmp = tempname; mkdir(tmp);
matp = fullfile(tmp, '10-AA-TEST-1-1-F1.mat');
Fs = 25600; n = 60000;
t = (0:n-1)'/Fs;
rpm = 1500*ones(n,1);
% v1.0 layout: [t, 8 dyno cols, tacho]
dyno = repmat(50*sin(t*3), 1, 8) + 5*randn(n,8);
tacho = sign(sin(2*pi*(rpm(1)/60).*t));   % crude pulse train (base MATLAB; no toolbox)
DATA = [t, dyno, tacho]; %#ok<NASGU>
metadata = struct('fileVersion',1.0,'Rate',Fs,'Feed',0.1,'CutDiameter',60,'MaxRPM',1500); %#ok<NASGU>
save(matp, 'DATA', 'metadata', '-v7');
outp = fullfile(tmp, 'grid.bin');
process_force(matp, tmp, struct('grid_out', outp, 'grid', struct('n', 512, 'method', 'splat', 'cv_arm_step', 10)));
assert(exist(outp,'file')==2, 'D1GR file not written');
fid = fopen(outp,'r','l'); hdr = fread(fid, 1, 'uint32'); Ncells = fread(fid, 1, 'uint32');
fidelity = fread(fid,1,'single'); armr = fread(fid,1,'single'); cellmm = fread(fid,1,'single');
body = fread(fid, Ncells*5, 'single'); fclose(fid);
assert(hdr == hex2dec('44314752'), 'bad D1GR magic');
assert(Ncells > 0, 'no cells emitted');
assert(numel(body) == Ncells*5, 'body length mismatch');
assert(cellmm > 0, 'bad cell_mm');
fprintf('PASS D1GR emit: N=%d fidelity=%.3f arm_ratio=%.3f cell=%.4f\n', Ncells, fidelity, armr, cellmm);
```

- [ ] **Step 2: Run to confirm the emit path fails**

Run: `matlab -batch "addpath('scripts/matlab'); test_grid_out"`
Expected: FAIL at `D1GR file not written` (branch not implemented yet).

- [ ] **Step 3: Add the `grid_out` branch to `process_force.m`**

In `scripts/matlab/process_force.m`, immediately after the `octree_out` branch's closing `end` (currently line 223, right before the `for k = 1:3` FRM PNG loop), insert:

```matlab
% ---- interpolated-grid emit: interpolate the FULL-resolution spiral onto a fine N×N grid
%      (splat/GPU or natural), compute a hold-out-arms fidelity number, and dump the kept
%      in-support cells as a little-endian D1GR binary for the host to octree-convert. Then STOP.
%      Format: uint32 magic 0x44314752 'D1GR', uint32 N, float32 fidelity, arm_ratio, cell_mm,
%      then float32 x,y,Fx,Fy,Fz [N].
if isfield(opts, 'grid_out') && ~isempty(opts.grid_out)
    g = struct('n', 2048, 'method', 'splat', 'cv_arm_step', 10);
    if isfield(opts, 'grid') && isstruct(opts.grid)
        fn = fieldnames(opts.grid);
        for ii = 1:numel(fn); g.(fn{ii}) = opts.grid.(fn{ii}); end
    end
    theta_cum = cumsum([0; ang_inc]);            % unwrapped cumulative angle (for arm indexing)
    theta_cum = theta_cum(1:cutend);
    gfx = axes_cut{1}; gfy = axes_cut{2}; gfz = axes_cut{3};
    [gx, gy, gFx, gFy, gFz, cellmm] = frm_grid_interp(xx0, yy0, gfx, gfy, gfz, g.n, g.method);
    [fidelity, arm_ratio] = frm_grid_fidelity(xx0, yy0, theta_cum, gfx, gfy, gfz, g.n, g.method, cellmm, g.cv_arm_step);
    Ng = numel(gx);
    fid = fopen(char(opts.grid_out), 'w', 'l');
    if fid < 0; error('process_force:grid', 'cannot open %s', opts.grid_out); end
    cleaner = onCleanup(@() fclose(fid));
    fwrite(fid, uint32(hex2dec('44314752')), 'uint32');
    fwrite(fid, uint32(Ng), 'uint32');
    fwrite(fid, single(fidelity), 'single');       % NaN -> reader maps to null
    fwrite(fid, single(arm_ratio), 'single');
    fwrite(fid, single(cellmm), 'single');
    fwrite(fid, single(gx(:)),  'single');
    fwrite(fid, single(gy(:)),  'single');
    fwrite(fid, single(gFx(:)), 'single');
    fwrite(fid, single(gFy(:)), 'single');
    fwrite(fid, single(gFz(:)), 'single');
    clear cleaner;                                  % flush+close now
    return;                                         % grid-only: skip full processing
end
```

- [ ] **Step 4: Provide the full-resolution spiral to the branch**

The `octree_out` branch computes `[ox, oy] = pol2cart(theta, rho)` locally at full resolution. The grid branch needs the same full-res cartesian spiral as `xx0, yy0`. Add this once, just above the `octree_out` branch (line 207), so both branches share it. Insert before `if isfield(opts, 'octree_out')`:

```matlab
[xx0, yy0] = pol2cart(theta, rho);               % full-resolution spiral (shared by octree/grid emit)
```

Then change the `octree_out` branch's line `[ox, oy] = pol2cart(theta, rho);` to reuse it:

```matlab
    ox = xx0; oy = yy0;                          % full resolution (shared)
```

- [ ] **Step 5: Run the harness to verify the emit passes**

Run: `matlab -batch "addpath('scripts/matlab'); test_grid_out"`
Expected: `PASS D1GR emit: N=… fidelity=… arm_ratio=… cell=…`, `ALL GRID TESTS PASSED`.

- [ ] **Step 6: Commit**

```bash
git add scripts/matlab/process_force.m scripts/matlab/test_grid_out.m
git commit -m "feat(force): grid_out branch emits D1GR interpolated-grid binary"
```

---

## Task 4: Orchestrator — `D1GR` reader + grid-octree handler

Near-clone of `process_octree_row`, reading `D1GR`, publishing to `grid/<op_id>/`, recording grid DB fields. Uses the **proven float32 attribute path** (int16 optimisation is Task 5).

**Files:**
- Modify: `scripts/force_orchestrator.py`
- Test: `scripts/test_grid_bin.py` (create)

**Interfaces:**
- Consumes: `unc_for`, `mlq`, `_ml_literal`, `_patch_octree_climits`, `detect_potree_converter`, `load_sampling_opts`, `OCTREE_DIR`, `Directus` (existing).
- Produces:
  - `_read_grid_bin(path) -> (n:int, fidelity:float|None, arm_ratio:float|None, cell_mm:float, x, y, fx, fy, fz)` (numpy arrays).
  - `load_grid_opts(conn) -> dict` — `{'n': int, 'method': str, 'cv_arm_step': 10}` from `force_crawler_state`.
  - `claim_grid(conn, limit=2) -> rows` (grid_octree_status='pending').
  - `process_grid_row(conn, row, exe, timeout, matlab_opts, grid_opts, potree_exe) -> str`.
  - `handle_grids(conn, exe) -> int`.

- [ ] **Step 1: Write the failing pytest for the reader**

Create `scripts/test_grid_bin.py`:

```python
"""Unit tests for the D1GR reader in force_orchestrator."""
import struct
import numpy as np
import force_orchestrator as fo


def _write_d1gr(path, x, y, fx, fy, fz, fidelity, arm_ratio, cell_mm):
    n = len(x)
    with open(path, "wb") as f:
        f.write(struct.pack("<II", 0x44314752, n))
        f.write(struct.pack("<fff", fidelity, arm_ratio, cell_mm))
        for arr in (x, y, fx, fy, fz):
            f.write(np.asarray(arr, dtype="<f4").tobytes())


def test_read_grid_bin_roundtrip(tmp_path):
    p = tmp_path / "grid.bin"
    x = [0.0, 1.0, 2.0]; y = [3.0, 4.0, 5.0]
    fx = [10.0, 11.0, 12.0]; fy = [1.0, 2.0, 3.0]; fz = [20.0, 21.0, 22.0]
    _write_d1gr(p, x, y, fx, fy, fz, 0.97, 4.2, 0.031)
    n, fid, ratio, cell, rx, ry, rfx, rfy, rfz = fo._read_grid_bin(str(p))
    assert n == 3
    assert abs(fid - 0.97) < 1e-6
    assert abs(ratio - 4.2) < 1e-6
    assert abs(cell - 0.031) < 1e-6
    assert np.allclose(rx, x) and np.allclose(rfz, fz)


def test_read_grid_bin_nan_fidelity(tmp_path):
    p = tmp_path / "grid.bin"
    _write_d1gr(p, [0.0], [0.0], [1.0], [1.0], [1.0], float("nan"), float("nan"), 0.5)
    n, fid, ratio, cell, *_ = fo._read_grid_bin(str(p))
    assert n == 1 and fid is None and ratio is None and abs(cell - 0.5) < 1e-6
```

- [ ] **Step 2: Run to confirm it fails**

Run: `cd scripts && python -m pytest test_grid_bin.py -v`
Expected: FAIL — `AttributeError: module 'force_orchestrator' has no attribute '_read_grid_bin'`.

- [ ] **Step 3: Implement the reader**

In `scripts/force_orchestrator.py`, after `_read_octree_bin` (line 454), add:

```python
def _read_grid_bin(path: str):
    """Read a D1GR interpolated-grid binary: magic, N, fidelity, arm_ratio, cell_mm header
    then float32 x,y,Fx,Fy,Fz [N]. NaN fidelity/arm_ratio -> None (stored NULL)."""
    import numpy as np
    with open(path, "rb") as f:
        magic, n = struct.unpack("<II", f.read(8))
        if magic != 0x44314752:
            raise RuntimeError(f"bad grid bin magic {magic:#x}")
        fidelity, arm_ratio, cell_mm = struct.unpack("<fff", f.read(12))
        a = np.frombuffer(f.read(n * 5 * 4), dtype="<f4")
    fid = None if fidelity != fidelity else float(fidelity)          # NaN check
    ratio = None if arm_ratio != arm_ratio else float(arm_ratio)
    return (n, fid, ratio, float(cell_mm),
            a[0:n], a[n:2 * n], a[2 * n:3 * n], a[3 * n:4 * n], a[4 * n:5 * n])
```

- [ ] **Step 4: Run the reader test to verify it passes**

Run: `cd scripts && python -m pytest test_grid_bin.py::test_read_grid_bin_roundtrip test_grid_bin.py::test_read_grid_bin_nan_fidelity -v`
Expected: 2 passed.

- [ ] **Step 5: Implement `load_grid_opts`, `claim_grid`, `process_grid_row`, `handle_grids`**

In `scripts/force_orchestrator.py`, after `handle_octrees` (line 575), add:

```python
# ------------------------------------------------- interpolated-grid octree build
def load_grid_opts(conn) -> dict:
    """Grid interpolation settings from force_crawler_state (density capped at 8192)."""
    opts = {"n": 2048, "method": "splat", "cv_arm_step": 10}
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT grid_density, grid_method FROM force_crawler_state "
                        "WHERE id='00000000-0000-0000-0000-000000000001'")
            row = cur.fetchone()
        if row:
            opts["n"] = min(8192, max(16, int(row["grid_density"] or 2048)))
            m = (row["grid_method"] or "splat").lower()
            opts["method"] = m if m in ("splat", "natural") else "splat"
    except psycopg2.Error:
        conn.rollback()
    return opts


def claim_grid(conn, limit: int = 2):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            WITH picked AS (
                SELECT id FROM machining_force_analysis
                 WHERE grid_octree_status='pending'
                 ORDER BY grid_octree_requested_at NULLS FIRST
                 LIMIT %s FOR UPDATE SKIP LOCKED
            )
            UPDATE machining_force_analysis a SET grid_octree_status='processing', updated_at=now()
              FROM picked WHERE a.id = picked.id
         RETURNING a.id, a.operation_id, a.pulses_per_rev,
                   (SELECT metadata->>'archive_path' FROM directus_files WHERE id = a.directus_files_id) AS archive_path
        """, [limit])
        rows = cur.fetchall()
    conn.commit()
    return rows


def process_grid_row(conn, row, exe: str, timeout: int, matlab_opts: dict,
                     grid_opts: dict, potree_exe: str) -> str:
    """MATLAB interpolates the spiral onto a grid + emits D1GR -> laspy LAS (force axes as
    float32 attrs) -> PotreeConverter -> publish under OCTREE_DIR/grid/<op_id>/ for Caddy.
    Records grid_octree_* + grid_fidelity + grid_arm_ratio + grid_cell_mm."""
    import numpy as np
    import laspy
    outdir = tempfile.mkdtemp(prefix="grid_", dir=os.environ.get("FORCE_WORKDIR"))
    try:
        if not row.get("archive_path"):
            raise ValueError("no archive .mat linked to this analysis row")
        binp = str(Path(outdir) / "grid.bin")
        opts = {k: int(v) for k, v in matlab_opts.items()}
        ppr = row.get("pulses_per_rev")
        if ppr and int(ppr) > 0:
            opts["pulses_per_rev"] = int(ppr)
        opts["grid_out"] = binp
        opts["grid"] = {"n": int(grid_opts["n"]), "method": str(grid_opts["method"]),
                        "cv_arm_step": int(grid_opts["cv_arm_step"])}
        stmt = (f"addpath('{mlq(str(MATLAB_SRC))}'); "
                f"process_force('{mlq(unc_for(row['archive_path']))}','{mlq(outdir)}',{_ml_literal(opts)})")
        p = subprocess.run([exe, "-batch", stmt], capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0 or not Path(binp).exists():
            tail = (p.stderr or p.stdout or "").strip().splitlines()[-5:]
            raise RuntimeError("matlab grid emit failed: " + " | ".join(tail))
        n, fidelity, arm_ratio, cell_mm, x, y, fx, fy, fz = _read_grid_bin(binp)
        if n == 0:
            raise RuntimeError("empty grid (no supported cells)")

        las_path = str(Path(outdir) / "grid.las")
        h = laspy.LasHeader(point_format=3)
        h.offsets = [float(x.min()), float(y.min()), 0.0]
        h.scales = [0.001, 0.001, 0.001]
        for nm in ("Fx", "Fy", "Fz"):
            h.add_extra_dim(laspy.ExtraBytesParams(name=nm, type=np.float32))
        las = laspy.LasData(h)
        las.x = x.astype(np.float64); las.y = y.astype(np.float64); las.z = np.zeros(n)
        las.Fx = fx; las.Fy = fy; las.Fz = fz
        lo, hi = float(fz.min()), float(fz.max())
        las.intensity = np.clip((fz - lo) / ((hi - lo) or 1.0) * 65535, 0, 65535).astype(np.uint16)
        las.write(las_path)

        octmp = str(Path(outdir) / "octree")
        pc = subprocess.run([potree_exe, las_path, "-o", octmp], capture_output=True, text=True, timeout=timeout)
        if pc.returncode != 0 or not (Path(octmp) / "metadata.json").exists():
            tail = (pc.stderr or pc.stdout or "").strip().splitlines()[-5:]
            raise RuntimeError("PotreeConverter failed: " + " | ".join(tail))
        _patch_octree_climits(Path(octmp) / "metadata.json", fx, fy, fz)

        op = str(row["operation_id"])
        dst = OCTREE_DIR / "grid" / op
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        dst.mkdir(parents=True, exist_ok=True)
        for fn in ("metadata.json", "hierarchy.bin", "octree.bin"):
            shutil.copy2(Path(octmp) / fn, dst / fn)

        with conn.cursor() as cur:
            cur.execute("UPDATE machining_force_analysis SET grid_octree_status='done', "
                        "grid_octree_path=%s, grid_octree_points=%s, grid_fidelity=%s, "
                        "grid_arm_ratio=%s, grid_cell_mm=%s, grid_octree_error=NULL, updated_at=now() "
                        "WHERE id=%s",
                        [f"grid/{op}", int(n), fidelity, arm_ratio, cell_mm, row["id"]])
        conn.commit()
        log.info("[GRID] %s -> grid/%s (%d cells, fidelity=%s)",
                 Path(row["archive_path"]).stem, op, n, fidelity)
        return "done"
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("UPDATE machining_force_analysis SET grid_octree_status='error', "
                        "grid_octree_error=%s, updated_at=now() WHERE id=%s", [str(e)[:2000], row["id"]])
        conn.commit()
        log.error("[GRID-ERR] %s", e)
        return "error"
    finally:
        shutil.rmtree(outdir, ignore_errors=True)


def handle_grids(conn, exe: str) -> int:
    """Build interpolated-grid octrees for any pending requests (needs PotreeConverter + laspy)."""
    potree_exe = detect_potree_converter()
    if not potree_exe:
        return 0
    try:
        import laspy  # noqa: F401
    except ImportError:
        log.warning("laspy not installed — grid octree requests left pending")
        return 0
    rows = claim_grid(conn)
    if not rows:
        return 0
    matlab_opts = load_sampling_opts(conn)
    grid_opts = load_grid_opts(conn)
    for r in rows:
        process_grid_row(conn, r, exe, 3600, matlab_opts, grid_opts, potree_exe)
    return len(rows)
```

Note: `grid_octree_path` is stored as `grid/<op_id>` so the dashboard's `octree-path` prop maps directly to the Caddy subpath.

- [ ] **Step 6: Wire into `run_queue` and `run_daemon`**

In `run_queue` (line 823), after `handle_octrees(conn, exe)`:

```python
    handle_octrees(conn, exe)             # build any pending Potree octrees
    handle_grids(conn, exe)               # build any pending interpolated-grid octrees
```

In `run_daemon` (line 912), after the `handle_octrees` block:

```python
                no = handle_octrees(conn, exe)
                if no:
                    log.info("daemon: built %d Potree octree(s)", no)

                ng = handle_grids(conn, exe)
                if ng:
                    log.info("daemon: built %d interpolated-grid octree(s)", ng)
```

- [ ] **Step 7: Run the reader tests again (regression)**

Run: `cd scripts && python -m pytest test_grid_bin.py -v`
Expected: 2 passed (the module still imports; new functions don't break the reader).

- [ ] **Step 8: Commit**

```bash
git add scripts/force_orchestrator.py scripts/test_grid_bin.py
git commit -m "feat(force): orchestrator grid-octree handler (D1GR -> Potree)"
```

---

## Task 5: Orchestrator — int16-scaled force storage (optimisation, test-gated)

Halve LAS attribute storage on the large grid octrees. Keep colour correctness identical to float32; if PotreeConverter's handling of scaled int16 extra dims is wrong, the round-trip test fails and we keep float32.

**Files:**
- Modify: `scripts/force_orchestrator.py` (`process_grid_row` LAS-writing block)
- Test: `scripts/test_grid_bin.py` (add a laspy round-trip test)

**Interfaces:**
- Consumes/produces: unchanged public API; internal LAS extra-dim encoding changes from float32 to int16 with per-axis `scales`/`offsets`.

- [ ] **Step 1: Write the failing int16 round-trip test**

Append to `scripts/test_grid_bin.py`:

```python
def test_int16_extra_dim_roundtrip(tmp_path):
    """laspy int16-scaled extra dim reconstructs Newton values within one quantisation step."""
    laspy = __import__("laspy"); np = __import__("numpy")
    fz = np.linspace(-120.0, 340.0, 5000).astype(np.float64)
    lo, hi = float(fz.min()), float(fz.max())
    scale = (hi - lo) / 65000.0 or 1.0          # int16 spans ~65k codes
    offset = (hi + lo) / 2.0
    h = laspy.LasHeader(point_format=3)
    h.offsets = [0.0, 0.0, 0.0]; h.scales = [0.001, 0.001, 0.001]
    h.add_extra_dim(laspy.ExtraBytesParams(name="Fz", type=np.int16, scales=[scale], offsets=[offset]))
    las = laspy.LasData(h)
    las.x = np.zeros(fz.size); las.y = np.zeros(fz.size); las.z = np.zeros(fz.size)
    las.Fz = fz
    p = tmp_path / "q.las"; las.write(str(p))
    back = laspy.read(str(p)).Fz
    assert np.max(np.abs(back - fz)) <= scale * 1.5     # within one code
```

- [ ] **Step 2: Run to confirm it passes at the laspy level**

Run: `cd scripts && python -m pytest test_grid_bin.py::test_int16_extra_dim_roundtrip -v`
Expected: PASS (this validates laspy's scaled-extra-dim contract before we rely on it).

- [ ] **Step 3: Switch `process_grid_row` LAS attributes to int16-scaled**

In `process_grid_row`, replace the float32 extra-dim block:

```python
        for nm in ("Fx", "Fy", "Fz"):
            h.add_extra_dim(laspy.ExtraBytesParams(name=nm, type=np.float32))
        las = laspy.LasData(h)
        las.x = x.astype(np.float64); las.y = y.astype(np.float64); las.z = np.zeros(n)
        las.Fx = fx; las.Fy = fy; las.Fz = fz
```

with int16-scaled dims (force is 12-bit at source → lossless):

```python
        arrays = {"Fx": fx, "Fy": fy, "Fz": fz}
        for nm, arr in arrays.items():
            lo_a, hi_a = float(np.min(arr)), float(np.max(arr))
            scale = ((hi_a - lo_a) / 65000.0) or 1.0     # int16 code span with headroom
            offset = (hi_a + lo_a) / 2.0
            h.add_extra_dim(laspy.ExtraBytesParams(name=nm, type=np.int16,
                                                   scales=[scale], offsets=[offset]))
        las = laspy.LasData(h)
        las.x = x.astype(np.float64); las.y = y.astype(np.float64); las.z = np.zeros(n)
        las.Fx = fx; las.Fy = fy; las.Fz = fz
```

`_patch_octree_climits` still receives the original float `fx/fy/fz` (Newtons), so the metadata min/max stay in Newtons and the shader/colorbar are unchanged.

- [ ] **Step 4: Verify end-to-end on a small op (manual, host)**

With the daemon running, request a grid build for one small op (Task 6 wires the UI; for now patch the DB directly):
```bash
docker compose exec -T db psql -U d1 -d d1_database -c \
 "UPDATE machining_force_analysis SET grid_octree_status='pending', grid_octree_requested_at=now() \
  WHERE octree_status='done' ORDER BY octree_points ASC LIMIT 1;"
```
Wait for the daemon log `[GRID] … -> grid/<op>`. Then confirm the served attribute colours match the raw octree (open the op, toggle Gridded after Task 6), and that `metadata.json` Fx/Fy/Fz `min`/`max` are in Newtons:
```bash
docker compose exec -T db psql -U d1 -d d1_database -c \
 "SELECT grid_octree_status, grid_octree_points, grid_fidelity, grid_cell_mm FROM machining_force_analysis WHERE grid_octree_status IS NOT NULL;"
```
Expected: `done`, sane point count, fidelity in [0,1], cell_mm > 0. **If the served grid octree colours look wrong** (potree-core mis-decoding int16), revert Step 3 to the float32 block and note it in the commit — the feature still works, just larger on disk.

- [ ] **Step 5: Commit**

```bash
git add scripts/force_orchestrator.py scripts/test_grid_bin.py
git commit -m "perf(force): int16-scaled force attrs for grid octrees (12-bit lossless)"
```

---

## Task 6: FrmOctree fill rendering

Size grid-octree points in world units (≈ cell spacing) so the grid reads as a continuous filled surface; add settings-driven LOD props.

**Files:**
- Modify: `core/extensions/d1-force-dashboard/src/FrmOctree.vue`

**Interfaces:**
- Consumes: existing props.
- Produces: new props `fill?: boolean`, `cellSize?: number` (mm), `minNodePx?: number`, `budgetCap?: number`. When `fill` is true, the vertex shader sizes points from `cellSize × pixels-per-mm`, clamped to `[1, 24]`px.

- [ ] **Step 1: Add the new props**

In the `defineProps` block (line 19), add:

```typescript
	totalPoints?: number;                     // octree's full point count -> sizes the LOD budget
	fill?: boolean;                           // grid octree: size points to tile cells into a surface
	cellSize?: number;                        // grid cell spacing (mm), for fill sizing
	minNodePx?: number;                       // Potree LOD cutoff (settings; default 1)
	budgetCap?: number;                       // Potree point-budget hard cap (settings; default 25M)
```

- [ ] **Step 2: Add a fill uniform + world-space sizing to the shader**

In `makeMaterial()` uniforms (line 69), add:

```typescript
				uZScale: { value: 0 },                        // world-unit height for the [0,1]-normalised Z
				uFill: { value: props.fill ? 1 : 0 },         // 1 = size points in world units (grid octree)
				uPxPerMm: { value: 1 },                       // updated each frame from the camera/viewport
				uCell: { value: props.cellSize || 1 },        // grid cell spacing (mm)
```

Replace the vertex shader's `gl_PointSize = uSize;` line with:

```glsl
					gl_PointSize = uFill > 0.5 ? clamp(uCell * uPxPerMm, 1.0, 24.0) : uSize;
```

and add the uniform declarations to the vertex shader header (next to `uniform float uSize;`):

```glsl
				uniform float uFill; uniform float uPxPerMm; uniform float uCell;
```

- [ ] **Step 3: Feed pixels-per-mm from the ortho camera each frame**

In the render `loop()` (line 213), inside `if (pco && potree && renderer && camera)`, before `renderer.render(...)`, add:

```typescript
				if (material && (props.fill)) {
					// orthographic: world width shown = (right-left)/zoom; px width = cssW*pixelRatio.
					const worldW = (camera.right - camera.left) / (camera.zoom || 1);
					const pxPerMm = worldW > 0 ? (renderer.domElement.width / worldW) : 1;
					material.uniforms.uPxPerMm.value = pxPerMm;
				}
```

- [ ] **Step 4: Apply settings-driven LOD props in `load()`**

In `load()` (line 163), replace the budget/minNodePixelSize lines:

```typescript
			potree.pointBudget = props.totalPoints && props.totalPoints > 0
				? Math.min(Math.ceil(props.totalPoints * 1.05), props.budgetCap || 25_000_000)
				: 15_000_000;
			pco = await potree.loadPointCloud('metadata.json', base);
			(pco as any).minNodePixelSize = props.minNodePx || 1;
```

- [ ] **Step 5: React to fill/cellSize changes**

After the existing `watch(() => props.pointSize, …)` (line 246), add:

```typescript
watch(() => [props.fill, props.cellSize], () => {
	if (material) {
		material.uniforms.uFill.value = props.fill ? 1 : 0;
		material.uniforms.uCell.value = props.cellSize || 1;
	}
});
```

- [ ] **Step 6: Build the extension**

Run: `cd core/extensions/d1-force-dashboard && npm run build`
Expected: build succeeds, `dist/` regenerated, no TypeScript errors.

- [ ] **Step 7: Commit**

```bash
git add core/extensions/d1-force-dashboard/src/FrmOctree.vue
git commit -m "feat(force): world-space fill rendering + settings LOD props in FrmOctree"
```

---

## Task 7: ForceDashboard — "Gridded" toggle, grid build, fidelity chip

Wire the grid octree into the dashboard: fetch grid fields, build-on-demand, mode-aware toggle, fidelity chip, octree tuning pass-through.

**Files:**
- Modify: `core/extensions/d1-force-dashboard/src/ForceDashboard.vue`

**Interfaces:**
- Consumes: `FrmOctree` props from Task 6 (`fill`, `cellSize`, `minNodePx`, `budgetCap`); grid DB columns from Task 1.

- [ ] **Step 1: Fetch the grid + settings columns**

In the detail-fetch `fields` array (line 499), extend the octree fields:

```typescript
						'octree_status', 'octree_path', 'octree_points',
						'grid_octree_status', 'grid_octree_path', 'grid_octree_points',
						'grid_fidelity', 'grid_arm_ratio', 'grid_cell_mm'],
```

- [ ] **Step 2: Read the new settings on mount**

In `onMounted` where `octreeThreshold` is fetched (line 337), extend the query and add refs. First add refs near `octreeThreshold` (line 112):

```typescript
const octreeThreshold = ref(5_000_000);
const octreeMinNodePx = ref(1);
const octreeBudgetCap = ref(25_000_000);
```

Then change the settings fetch (line 337) to:

```typescript
				const s = await api.get('/items/force_crawler_state', { params: { fields: ['live_cache_points', 'octree_threshold', 'octree_min_node_px', 'octree_budget_cap'], limit: 1 } });
				const row = s.data?.data?.[0] || s.data?.data;
				const cap = Number(row?.octree_threshold ?? row?.live_cache_points);
				if (Number.isFinite(cap) && cap > 0) octreeThreshold.value = cap;
				const mnp = Number(row?.octree_min_node_px);
				if (Number.isFinite(mnp) && mnp > 0) octreeMinNodePx.value = mnp;
				const bc = Number(row?.octree_budget_cap);
				if (Number.isFinite(bc) && bc > 0) octreeBudgetCap.value = bc;
```

- [ ] **Step 3: Add grid state, computeds, and `buildGridOctree`**

After the `buildOctree` function (line 148), add:

```typescript
// ---- Interpolated-grid octree (Gridded + Full-res) ---------------------------------
const gridAvailable = computed(() => detail.value?.grid_octree_status === 'done' && !!detail.value?.grid_octree_path);
// "Gridded" is a single mode-aware flag: in Live it drives client-side gridCloud binning
// (the old `gridding`); in Full-res it selects the interpolated-grid octree.
const gridActive = computed(() => gridding.value && octreeMode.value && gridAvailable.value);
const gridFidelityPct = computed(() => {
	const f = detail.value?.grid_fidelity;
	return (f == null || Number.isNaN(Number(f))) ? null : Math.round(Number(f) * 100);
});
async function buildGridOctree() {
	const d = detail.value;
	if (!d?.id || buildingOctree.value) return;
	buildingOctree.value = true; octreeMsg.value = 'Requesting interpolated-grid build on the host…';
	try {
		await api.patch(`/items/machining_force_analysis/${d.id}`, { grid_octree_status: 'pending', grid_octree_requested_at: new Date().toISOString() });
		octreeMsg.value = 'Interpolating grid on the host (minutes for large ops)…';
		const deadline = Date.now() + 15 * 60 * 1000;
		while (Date.now() < deadline) {
			await new Promise((r) => setTimeout(r, 3000));
			const res = await api.get(`/items/machining_force_analysis/${d.id}`, { params: { fields: ['grid_octree_status', 'grid_octree_path', 'grid_octree_points', 'grid_octree_error', 'grid_fidelity', 'grid_arm_ratio', 'grid_cell_mm'] } });
			const row = res.data?.data;
			if (row?.grid_octree_status === 'done' && row.grid_octree_path) {
				detail.value = { ...detail.value, grid_octree_status: 'done', grid_octree_path: row.grid_octree_path,
					grid_octree_points: row.grid_octree_points, grid_fidelity: row.grid_fidelity,
					grid_arm_ratio: row.grid_arm_ratio, grid_cell_mm: row.grid_cell_mm };
				octreeMsg.value = null; return;
			}
			if (row?.grid_octree_status === 'error') { octreeMsg.value = `Grid build failed: ${row.grid_octree_error || 'unknown'}`; return; }
		}
		octreeMsg.value = 'Still building — check back shortly (is the force orchestrator running?).';
	} catch (e: any) {
		octreeMsg.value = e?.response?.status === 403 ? 'Not permitted (admin only) to request a host build.' : (e?.message || 'grid request failed');
	} finally { buildingOctree.value = false; }
}
// When the user turns on Gridded in Full-res and no grid octree exists yet, build it.
watch(() => [gridding.value, octreeMode.value], () => {
	if (gridding.value && octreeMode.value && !gridAvailable.value && !buildingOctree.value) buildGridOctree();
});
```

- [ ] **Step 4: Point FrmOctree at the grid octree when active + fill props**

Update the `<FrmOctree>` tag (line 1003) to choose the path and enable fill in grid mode:

```html
									<FrmOctree v-else-if="octreeOn" ref="frmOctreeRef"
										:octree-path="gridActive ? detail.grid_octree_path : detail.octree_path" :axis="axis"
										:colormap="colormap" :point-size="pointSize" :cmin="cmin" :cmax="cmax"
										:z-series="zSeries" :z-scale="zScale"
										:total-points="gridActive ? Number(detail.grid_octree_points) : fullResPoints"
										:fill="gridActive" :cell-size="Number(detail.grid_cell_mm) || 1"
										:min-node-px="octreeMinNodePx" :budget-cap="octreeBudgetCap"
										@climits="onClimits" @points="displayedPoints = $event" />
```

(Prop names match Task 6 exactly: `:fill` ⇔ `fill`, `:cell-size` ⇔ `cellSize`, `:min-node-px` ⇔ `minNodePx`, `:budget-cap` ⇔ `budgetCap`.)

- [ ] **Step 5: Rename the "Grid binning" checkbox to "Gridded"**

Change line 904:

```html
										<label class="chk"><input v-model="gridding" type="checkbox" /> Gridded</label>
```

- [ ] **Step 6: Add the fidelity chip to the FRM header**

After the `frm-res` span (line 977), add:

```html
									<span v-if="gridActive && gridFidelityPct != null" class="frm-fid"
										:class="{ good: gridFidelityPct >= 95 }"
										:title="`Interpolated-grid fidelity (hold-out-arms CV). Arm/cell ratio ${detail.grid_arm_ratio?.toFixed?.(1) ?? '—'}`">
										grid · fidelity ~{{ gridFidelityPct }}%
									</span>
									<span v-else-if="gridActive" class="frm-fid" title="Fidelity could not be computed (too few arms)">grid · fidelity n/a</span>
```

Add the chip styles near the `.frm-res` style rule (search the `<style scoped>` block for `.frm-res`):

```css
.frm-fid { font-size: 10px; padding: 1px 7px; border-radius: 99px; font-weight: 700;
	color: #b45309; background: color-mix(in srgb, #d97706 14%, transparent); white-space: nowrap; }
.frm-fid.good { color: #15803d; background: color-mix(in srgb, #16a34a 14%, transparent); }
```

- [ ] **Step 7: Reset `gridding` sensibly on op change (keep existing reset)**

The existing reset at line 662 (`gridding.value = false`) already runs on op switch — leave it. Confirm the auto-route watch (line 176) is unaffected (it doesn't touch `gridding`).

- [ ] **Step 8: Build the extension**

Run: `cd core/extensions/d1-force-dashboard && npm run build`
Expected: build succeeds, no TS errors.

- [ ] **Step 9: Restart Directus + smoke check**

Run: `docker compose restart directus`
Then open the dashboard, pick a large op with a built raw octree, switch to Full-res, toggle **Gridded** → a build is requested; when done the map fills and the fidelity chip appears.

- [ ] **Step 10: Commit**

```bash
git add core/extensions/d1-force-dashboard/src/ForceDashboard.vue core/extensions/d1-force-dashboard/src/FrmOctree.vue
git commit -m "feat(force): Gridded toggle -> interpolated-grid octree + fidelity chip"
```

---

## Task 8: Crawler settings — "Gridding & octree" block

Expose the new tuning knobs on the crawler page.

**Files:**
- Modify: `core/extensions/d1-force-crawler/src/Crawler.vue`

**Interfaces:**
- Consumes: `force_crawler_state` settings columns from Task 1.

- [ ] **Step 1: Extend the draft + loadState + saveSettings**

In the `draft` ref (line 16), add the five fields:

```typescript
	live_cache_points: 250000, pulses_per_rev: 1,
	grid_density: 2048, grid_method: 'splat', octree_threshold: 5000000,
	octree_min_node_px: 1, octree_budget_cap: 25000000,
```

In `loadState` (line 29), add to the assigned `draft.value = { … }`:

```typescript
				live_cache_points: state.value.live_cache_points,
				pulses_per_rev: state.value.pulses_per_rev,
				grid_density: state.value.grid_density ?? 2048,
				grid_method: state.value.grid_method ?? 'splat',
				octree_threshold: state.value.octree_threshold ?? state.value.live_cache_points,
				octree_min_node_px: Number(state.value.octree_min_node_px ?? 1),
				octree_budget_cap: state.value.octree_budget_cap ?? 25000000,
```

In `saveSettings` (line 102), add to the patched object (with clamps):

```typescript
				pulses_per_rev: Math.max(1, Number(draft.value.pulses_per_rev) || 1),
				grid_density: Math.min(8192, Math.max(16, Number(draft.value.grid_density) || 2048)),
				grid_method: draft.value.grid_method === 'natural' ? 'natural' : 'splat',
				octree_threshold: Math.max(1000, Number(draft.value.octree_threshold) || 5000000),
				octree_min_node_px: Math.max(0.1, Number(draft.value.octree_min_node_px) || 1),
				octree_budget_cap: Math.max(1000000, Number(draft.value.octree_budget_cap) || 25000000),
```

- [ ] **Step 2: Add the settings block to the template**

After the Sampling `<div class="form">…</div>` block that ends at line 266 (the one containing the `setting-note`), before the Save button (line 267), insert:

```html
							<div class="form-sep">Gridding &amp; octree (applies to builds after saving)</div>
							<div class="form">
								<label>Grid density N (≤ 8192)<input v-model.number="draft.grid_density" type="number" min="16" max="8192" step="128" @input="dirty = true" /></label>
								<label>Grid method
									<select v-model="draft.grid_method" @change="dirty = true">
										<option value="splat">splat (Gaussian, GPU)</option>
										<option value="natural">natural (Delaunay)</option>
									</select>
								</label>
								<label>Octree auto-route threshold (pts)<input v-model.number="draft.octree_threshold" type="number" min="1000" step="100000" @input="dirty = true" /></label>
								<label>Octree min node px<input v-model.number="draft.octree_min_node_px" type="number" min="0.1" step="0.5" @input="dirty = true" /></label>
								<label>Octree budget cap (pts)<input v-model.number="draft.octree_budget_cap" type="number" min="1000000" step="1000000" @input="dirty = true" /></label>
								<p class="setting-note">The interpolated grid fills the sparse spiral at deep zoom (N×N cells; <b>splat</b> is GPU-accelerated). Maps above the <b>auto-route threshold</b> default to the octree view. Lower <b>min node px</b> streams more detail; the <b>budget cap</b> bounds GPU memory.</p>
							</div>
```

The `grid_method` `<select>` needs the input styling — it inherits `.form input`; add `select` to that selector if needed (search `.form input` in the `<style scoped>` and change to `.form input, .form select`).

- [ ] **Step 3: Build the extension**

Run: `cd core/extensions/d1-force-crawler && npm run build`
Expected: build succeeds, no TS errors.

- [ ] **Step 4: Restart Directus + verify round-trip**

Run: `docker compose restart directus`
Open the Force Crawler page: the "Gridding & octree" block shows current values; change `grid_density` to 3072, Save, reload the page → value persists.

- [ ] **Step 5: Commit**

```bash
git add core/extensions/d1-force-crawler/src/Crawler.vue
git commit -m "feat(force): crawler Gridding & octree settings block"
```

---

## Task 9: Playwright end-to-end

Extend the force-dashboard spec to cover the Gridded toggle, fill rendering, fidelity chip, and settings round-trip.

**Files:**
- Modify: `tests/ui/specs/11-force-dashboard.spec.ts`

**Interfaces:**
- Consumes: the shipped dashboard + crawler UI from Tasks 7–8. Reuses the headless SwiftShader WebGL harness already used by the octree tests.

- [ ] **Step 1: Read the existing spec to match its helpers/fixtures**

Run: open `tests/ui/specs/11-force-dashboard.spec.ts` and note the login/setup helpers, how it selects an op with a built octree, and the `.frm-octree`/`.error` locators already used by the mode-switch test.

- [ ] **Step 2: Add the Gridded test**

Append a test that:
1. Logs in, opens the dashboard, selects an op that already has `octree_status='done'` (reuse the existing octree-op selector).
2. Enables Full-res (`.tbtn:has-text("Full-res")`), waits for `.frm-octree canvas` and no `.frm-octree .error`.
3. Enables Gridded (`.chk:has-text("Gridded") input`). Because a fresh grid octree may need building (minutes), the test **pre-seeds** the grid octree by patching the row via the API before the UI step (mirror how the octree tests ensure a built octree), so the toggle loads immediately.
4. Asserts the fidelity chip renders: `await expect(page.locator('.frm-fid')).toBeVisible()` and its text matches `/fidelity ~\d+%|fidelity n\/a/`.
5. Asserts no octree error overlay after the swap.

Concrete test (adapt selectors to the file's existing patterns):

```typescript
test('Gridded toggle loads the interpolated-grid octree with a fidelity chip', async ({ page, request }) => {
  await login(page);                                   // reuse the spec's existing helper
  await openForceDashboard(page);                      // reuse existing helper
  const opId = await selectOpWithOctree(page, request);// reuse/adapt the octree-op helper

  // Pre-seed a grid octree so the toggle doesn't wait minutes on a host build.
  await ensureGridOctree(request, opId);               // patches grid_octree_status='pending', polls to done
  await page.reload();
  await selectSameOp(page, opId);

  await page.locator('.tbtn', { hasText: 'Full-res' }).click();
  await expect(page.locator('.frm-octree canvas')).toBeVisible();
  await page.locator('.chk:has-text("Gridded") input').check();

  const fid = page.locator('.frm-fid');
  await expect(fid).toBeVisible({ timeout: 20_000 });
  await expect(fid).toHaveText(/fidelity ~\d+%|fidelity n\/a/);
  await expect(page.locator('.frm-octree .error')).toHaveCount(0);
});
```

If pre-seeding a real host build is impractical in CI (no MATLAB/PotreeConverter), gate this test with `test.skip(!process.env.FORCE_HOST_TESTS, 'needs host MATLAB+PotreeConverter')` — matching how the existing octree build test is gated (check the spec for the existing guard and reuse it).

- [ ] **Step 3: Add a settings round-trip test (crawler)**

```typescript
test('crawler persists grid density', async ({ page }) => {
  await login(page);
  await page.goto('/admin/force-crawler');             // adapt to the module's route
  const dens = page.locator('label:has-text("Grid density") input');
  await dens.fill('3072');
  await page.locator('button:has-text("Save settings")').click();
  await page.reload();
  await expect(dens).toHaveValue('3072');
});
```

- [ ] **Step 4: Run the spec**

Run: `cd tests/ui && npx playwright test specs/11-force-dashboard.spec.ts`
Expected: the mode-switch tests still pass; the new Gridded test passes (or is skipped when `FORCE_HOST_TESTS` is unset); the crawler settings test passes.

- [ ] **Step 5: Commit**

```bash
git add tests/ui/specs/11-force-dashboard.spec.ts
git commit -m "test(force): Playwright for Gridded octree + crawler grid settings"
```

---

## Verification (whole feature)

- **MATLAB:** `matlab -batch "addpath('scripts/matlab'); test_grid_out"` → all grid + D1GR asserts pass; splat and natural both produce non-empty masked grids with fidelity ∈ [0,1] and cell > 0.
- **Orchestrator:** `cd scripts && python -m pytest test_grid_bin.py -v` → reader + int16 round-trip pass. A real host build sets `grid_octree_status='done'`, `grid_fidelity`, `grid_cell_mm`, and writes `infra/octrees/grid/<op>/{metadata,hierarchy,octree}.*`.
- **Dashboard:** Full-res + Gridded on a large op fills the map (no dot gaps at moderate zoom), the fidelity chip shows green ≥95% / amber below, and the resolution readout still tracks. Live + Gridded still does client-side `gridCloud` binning (unchanged). Full-res un-gridded still loads the raw octree (unchanged).
- **Settings:** the crawler "Gridding & octree" block round-trips (save → reload → persisted); `octree_threshold` seeded from `live_cache_points`; the dashboard auto-routes on `octree_threshold` and passes `octree_min_node_px`/`octree_budget_cap` to `FrmOctree`.
- **Playwright:** `specs/11-force-dashboard.spec.ts` green (host-build test skipped without `FORCE_HOST_TESTS`).

## Notes / decisions folded in

- **`cell_mm` in the D1GR header** (a small addition to the spec's format) makes fill-point sizing exact rather than estimated from the bounding box.
- **`grid_octree_path` stored as `grid/<op_id>`** so the `FrmOctree` `octree-path` prop maps straight to the Caddy subpath with no client-side prefixing.
- **int16 storage is Task 5, after a working float32 path (Task 4)** — sequenced so the feature works before the storage optimisation, with a round-trip test gate and a documented float32 fallback if potree-core mis-decodes scaled int16.
- **"Gridded" is one flag (`gridding`)** reused across modes: client `gridCloud` in Live, interpolated-grid octree in Full-res (per the spec's unified toggle).
