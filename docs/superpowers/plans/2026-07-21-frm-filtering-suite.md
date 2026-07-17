# FRM Filtering Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Interactive signal filtering for the FRM dashboard: host filter-service preview in two linked raw|filtered viewports, per-op chains + named profiles, and a MATLAB bake that applies the identical chain to all derived outputs.

**Architecture:** per spec `docs/superpowers/specs/2026-07-21-frm-filtering-suite-design.md`. New `services/filter-service` container (FastAPI+scipy) behind Caddy `/filter/*`; `filter_chain` jsonb on `machining_force_analysis` + `filter_profiles` table; `scripts/matlab/frm_filters.m` applied in `run_analysis` before all outputs; ForceDashboard Filters accordion + compare mode with a shared-view prop on FrmCloud.

**Tech Stack:** Python 3.12/FastAPI/scipy, MATLAB R2025a (Signal Processing Toolbox: hampel/butter/filtfilt/iirnotch), Vue 3/three.js, Postgres/dbmate, Caddy, Docker compose.

## Global Constraints
- Chain JSON shape exactly as the spec (despike/detrend/lowpass/notch, fixed order).
- Zero-phase filtering everywhere (sosfiltfilt/filtfilt); notch at `harmonics × mean_rpm/60`.
- Defaults: target_points 1.5M, debounce 400ms, LRU 4, despike 11/5σ, HP 5 Hz, LP 2 kHz o4, notch Q30 h1–3.
- Parity tolerance: full-chain RMS diff < 1e-6 × signal RMS.
- Never commit .env/.crt/overrides; restart directus after extension rebuilds; migrations via dbmate container.

### Task 1: Migration — filter_chain + filter_profiles (+ Directus registration)
Files: `db/migrations/20260721000097_filter_chain.sql`. Steps: write (ALTER machining_force_analysis ADD filter_chain jsonb; CREATE filter_profiles (id uuid default gen_random_uuid() PK, name text UNIQUE NOT NULL, chain jsonb NOT NULL, created_at timestamptz default now()); register `filter_profiles` in directus_collections + fields, filter_chain field on machining_force_analysis) → apply → verify columns → commit.

### Task 2: filter-service container
Files: `services/filter-service/{app.py,filters.py,d1lc.py,requirements.txt,Dockerfile,test_filters.py}`; modify `docker-compose.yml`, `infra/caddy/Caddyfile`.
- `filters.py`: `apply_chain(fx, fy, fz, fs, mean_rpm, chain) -> (fx, fy, fz, skipped)` implementing the four stages (hampel via rolling median+MAD, scipy.signal butter/sosfiltfilt, iirnotch/filtfilt per harmonic); validation errors raise ValueError.
- `d1lc.py`: parse/serialise the D1LC cache format + stride decimation.
- `app.py`: FastAPI; `POST /filter` (fetch `/assets/{id}` from `http://directus:8055` forwarding the caller's Cookie/Authorization; parsed-cache LRU 4; apply chain; return D1LC bytes, `X-Filter-Skipped` header), `POST /filter/fft` (one axis → {f,amp} ~3k pts via scipy.signal.welch), `GET /health`.
- Compose service `filter-service` (build ./services/filter-service, network d1net, no ports) + Caddy `handle_path /filter/*` → `reverse_proxy filter-service:8000`.
- pytest: chain math on synthetics, D1LC round-trip, validation. Restart proxy; curl /filter/health via Caddy.

### Task 3: MATLAB frm_filters + orchestrator threading
Files: `scripts/matlab/frm_filters.m` (public `apply_filter_chain`), modify `scripts/matlab/process_force.m` (jsondecode opts.filter_chain string; apply after rpm computed, before series/metrics), `scripts/force_orchestrator.py` (RETURNING + opts threading of `filter_chain::text`, all four claim paths), extend `scripts/matlab/test_grid_out.m` with a filtered synthetic check. Parity test: `services/filter-service/test_parity.py` writes synthetic CSV + chain JSON, runs scipy; MATLAB harness `scripts/matlab/test_filter_parity.m` reads same CSV, writes filtered CSV; pytest compares RMS diff < 1e-6×RMS.

### Task 4: Dashboard — Filters accordion, compare mode, linked views, FFT overlay, badge
Files: modify `core/extensions/d1-force-dashboard/src/{ForceDashboard.vue,FrmCloud.vue,liveCache.ts,ForceChart.vue}`, create `src/filterChain.ts` (types, defaults, chainHash, validation, service calls).
- FrmCloud: optional `sharedView` prop (reactive {cx,cy,span,active}); when set, view read/writes go through it; optional `cacheOverride` prop (a parsed Cache) that bypasses the id-based load (used by the filtered pane); label prop for the corner badge.
- ForceDashboard: `filterChain` ref seeded from detail.filter_chain; Filters accordion UI (stage toggles + params, profile dropdown/save/delete via /items/filter_profiles, Bake = patch filter_chain + status='pending' + poll, Clear); debounced service call → parsed filtered cache stored in liveCache LRU under `id#hash` → compare rendering: two FrmCloud panes (raw uses existing path; filtered uses cacheOverride), sharedView object, shared climits from the raw pane, Z select disabled in compare, filtered-pane error notice; "⚙ filtered" badge when detail.filter_chain non-null.
- ForceChart: optional `overlay` prop ({f,amp}) drawn as a dashed path (FFT chart only).
- Build + restart + manual smoke.

### Task 5: Verification
Playwright additions to spec-11: enable LP stage → two `.frm-cloud` panes; drag pane A, assert both share view (read exposed bounds via evaluate or compare screenshots); profile save/load; badge. Full suite + pytest + MATLAB harness green. Update memory backlog. Commits per task.
