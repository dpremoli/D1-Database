# Diagnostics Phase C — Preview Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a `diag-service` container that re-runs a diagnostics recipe from the published `base.d1an` intermediate — no MATLAB, no archive — and return the resulting D1AN column bytes, reachable same-origin at `/diag/preview`.

**Architecture:** A small FastAPI service mirroring `plugins/filter-service` exactly: forwards the caller's Directus credentials for per-request authorization (IDOR guard), reads `base.d1an` off the same `./infra/octrees` bind mount Caddy serves, calls the *same* `run_recipe` the orchestrator's bake calls (so preview and bake cannot diverge), and returns `write_d1an`-format bytes. Parsed `base.d1an` files and computed results are LRU-cached in memory. Caddy routes `/diag/*` to it, no published port.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, httpx, NumPy, SciPy, scikit-learn, pytest; Docker Compose; Caddy.

**Spec:** `docs/superpowers/specs/2026-09-01-diagnostics-recipe-workbench-design.md` (Component 4 — Preview)

## Global Constraints

- `scripts/diag/` is imported verbatim by this service — do not modify it, and do not copy-paste any of its logic into the service. `run_recipe`, `seed_columns`, `write_d1an`, `read_d1an`, `recipe_hash` are the entry points.
- Authorization must forward the caller's own `Authorization` / `Cookie` headers to Directus and re-check on every request including cache hits — this is the IDOR hole `filter-service` commit `32fb4b7` fixed. Never use a service account.
- The service has no published port. It is reached only through Caddy at `/diag/*`, same tailnet-trust posture as `/filter/*`.
- `base.d1an` holds exactly `t, rev, x, y, sig` on the angular grid (~18k rows). It is the resume point for `derived`-tier steps; the service never invokes MATLAB.
- Preview and bake run the identical `run_recipe` code path. Any divergence is a bug.
- Run Python service tests with `py -m pytest plugins/diag-service/tests/ -v` from the repo root.
- Lint touched Python with `py -m ruff check plugins/diag-service/`.

---

## File Structure

| File | Responsibility |
|---|---|
| `plugins/diag-service/Dockerfile` | **Create.** Build from repo root; copy `scripts/diag/` + `plugins/diag-service/app/` + `tests/` into the image. |
| `plugins/diag-service/requirements.txt` | **Create.** fastapi, uvicorn[standard], httpx, numpy, scipy, scikit-learn, pytest. |
| `plugins/diag-service/app/__init__.py` | **Create.** Empty. |
| `plugins/diag-service/app/main.py` | **Create.** The FastAPI app: `/health`, `POST /diag/preview`, auth forward, base.d1an loader, two LRUs. |
| `plugins/diag-service/tests/__init__.py` | **Create.** Empty. |
| `plugins/diag-service/tests/test_preview.py` | **Create.** Unit tests over the compute path with the Directus call stubbed. |
| `docker-compose.yml` | **Modify.** Add the `diag-service` block after `filter-service`. |
| `infra/caddy/Caddyfile` | **Modify.** Add `handle_path /diag/*` after the `/filter/*` block. |

---

## Task 1: The diag-service FastAPI app

**Files:**
- Create: `plugins/diag-service/app/__init__.py` (empty)
- Create: `plugins/diag-service/app/main.py`
- Create: `plugins/diag-service/tests/__init__.py` (empty)
- Create: `plugins/diag-service/tests/test_preview.py`
- Create: `plugins/diag-service/requirements.txt`

**Interfaces:**
- Consumes: `diag.runner.run_recipe`, `diag.runner.seed_columns` (unused here but import-safe), `diag.d1an.write_d1an`, `diag.d1an.read_d1an`, `diag.recipe.recipe_hash`, `diag.registry.STEPS`.
- Produces: an ASGI `app` with `GET /health` and `POST /diag/preview`. `POST /diag/preview` request body `{ "analysis_id": str, "recipe": dict, "from_step": int | null, "layers": dict | null }`; response is `application/octet-stream` D1AN bytes (magic `0x4431414E`) on success, JSON error otherwise.

- [ ] **Step 1: Write `requirements.txt`**

`plugins/diag-service/requirements.txt`:

```
fastapi==0.115.*
uvicorn[standard]==0.30.*
httpx==0.27.*
numpy==2.*
scipy==1.14.*
scikit-learn==1.5.*
pytest==8.*
```

- [ ] **Step 2: Write the failing test**

Create `plugins/diag-service/tests/__init__.py` (empty) and `plugins/diag-service/tests/test_preview.py`:

```python
"""diag-service preview tests. The Directus authorization call is stubbed; the compute
path is exercised for real against a base.d1an written from the shared diag test synthetic,
and its output is asserted identical to calling run_recipe directly (preview == bake path).
"""

from __future__ import annotations

import io
import os
import sys

import numpy as np
import pytest

REPO = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "plugins", "diag-service"))

from diag.d1an import read_d1an, write_d1an  # noqa: E402
from diag.recipe import DEFAULT_RECIPE  # noqa: E402
from diag.runner import run_recipe, seed_columns  # noqa: E402

# conftest of the main diag suite builds the synthetic; re-use it directly.
sys.path.insert(0, os.path.join(REPO, "tests", "scripts", "diag"))
from conftest import cache_of, synthetic_cut  # noqa: E402


BASE_COLUMNS = ("t", "rev", "x", "y", "sig")


def _base_d1an(tmp_path) -> str:
    """Write a base.d1an exactly as process_diag_row does: run the default recipe stopped
    after angular_resample with emit=BASE_COLUMNS."""
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = synthetic_cut()
    cache = cache_of(t, fx, fy, fz, rpm, revs, fs)
    stop = next(i for i, s in enumerate(DEFAULT_RECIPE["steps"]) if s["op"] == "angular_resample")
    cols, _ = run_recipe(DEFAULT_RECIPE, seed_columns(cache, x, y), stop_after=stop, emit=BASE_COLUMNS)
    p = str(tmp_path / "base.d1an")
    write_d1an(p, cols)
    return p


def _expected_full(tmp_path):
    """What a full bake produces for the same cut — the ground truth preview must match."""
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = synthetic_cut()
    cols, metrics = run_recipe(DEFAULT_RECIPE, seed_columns(cache_of(t, fx, fy, fz, rpm, revs, fs), x, y))
    return cols, metrics


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient with base.d1an on a fake octree root and Directus auth stubbed to allow."""
    root = tmp_path / "octrees" / "diag" / "op-under-test"
    root.mkdir(parents=True)
    src = _base_d1an(tmp_path)
    os.replace(src, str(root / "base.d1an"))

    monkeypatch.setenv("OCTREE_ROOT", str(tmp_path / "octrees"))
    from fastapi.testclient import TestClient

    import app.main as m

    async def _fake_resolve(analysis_id, req):
        assert analysis_id == "analysis-1"
        return {"diag_path": "op-under-test", "diag_status": "done"}

    monkeypatch.setattr(m, "_resolve_and_authorize", _fake_resolve)
    return TestClient(m.app)


def test_health(client):
    assert client.get("/health").json()["ok"] is True


def test_preview_matches_a_full_bake(client, tmp_path):
    r = client.post("/diag/preview", json={
        "analysis_id": "analysis-1", "recipe": DEFAULT_RECIPE, "from_step": None, "layers": None,
    })
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/octet-stream"

    got = read_d1an_bytes(r.content)
    want, _ = _expected_full(tmp_path)
    assert set(got) == set(want)
    for name in want:
        np.testing.assert_array_equal(got[name], want[name], err_msg=f"column {name}")


def test_preview_reflects_a_param_change(client):
    hot = {"recipe_version": 1, "name": "x", "steps": [dict(s) for s in DEFAULT_RECIPE["steps"]]}
    for s in hot["steps"]:
        if s["op"] == "getis_ord":
            s["params"] = {**s["params"], "k": 50}
    a = client.post("/diag/preview", json={"analysis_id": "analysis-1", "recipe": DEFAULT_RECIPE, "from_step": None, "layers": None})
    b = client.post("/diag/preview", json={"analysis_id": "analysis-1", "recipe": hot, "from_step": None, "layers": None})
    assert a.status_code == b.status_code == 200
    ga, gb = read_d1an_bytes(a.content), read_d1an_bytes(b.content)
    assert not np.array_equal(ga["gi_star"], gb["gi_star"]), "k=30 vs k=50 must change gi_star"


def test_missing_analysis_is_409(client, monkeypatch):
    import app.main as m

    async def _not_done(analysis_id, req):
        return {"diag_path": None, "diag_status": "pending"}

    monkeypatch.setattr(m, "_resolve_and_authorize", _not_done)
    from fastapi.testclient import TestClient
    c = TestClient(m.app)
    r = c.post("/diag/preview", json={"analysis_id": "x", "recipe": DEFAULT_RECIPE, "from_step": None, "layers": None})
    assert r.status_code == 409


def read_d1an_bytes(buf: bytes) -> dict[str, np.ndarray]:
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".d1an", delete=False) as f:
        f.write(buf)
        path = f.name
    try:
        return read_d1an(path)
    finally:
        os.unlink(path)
```

- [ ] **Step 3: Run the test to confirm it fails**

Run: `py -m pytest plugins/diag-service/tests/test_preview.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 4: Write `app/__init__.py` and `app/main.py`**

Create `plugins/diag-service/app/__init__.py` (empty).

Create `plugins/diag-service/app/main.py`:

```python
"""diag-service: interactive diagnostics-recipe previews.

The browser POSTs a recipe + an analysis-row id. We forward the caller's own Directus
credentials to resolve that row (403 if they may not see it — an IDOR guard identical to
filter-service's), read the row's published base.d1an off the octree bind mount, and re-run
the recipe from the angular-domain state using the SAME run_recipe the orchestrator's bake
calls. No MATLAB, no archive. Result is D1AN column bytes. Served same-origin by Caddy at
/diag/*.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from collections import OrderedDict

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

# scripts/diag is copied to /app/diag in the image; on a dev host it is on sys.path via the
# test bootstrap. Import the SAME modules the orchestrator uses — never reimplement them.
_HERE = os.path.dirname(__file__)
for _p in (os.path.join(_HERE, ".."), os.path.join(_HERE, "..", "..", "..", "scripts")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

from diag.d1an import read_d1an, write_d1an  # noqa: E402
from diag.recipe import recipe_hash  # noqa: E402
from diag.registry import STEPS  # noqa: E402
from diag.runner import run_recipe  # noqa: E402

DIRECTUS_URL = os.environ.get("DIRECTUS_URL", "http://directus:8055").rstrip("/")
OCTREE_ROOT = os.environ.get("OCTREE_ROOT", "/srv/octrees")
BASE_LRU_CAP = int(os.environ.get("BASE_LRU", "6"))
RESULT_LRU_CAP = int(os.environ.get("RESULT_LRU", "24"))

app = FastAPI(title="d1-diag-service")

_cors = [o.strip() for o in os.environ.get("DIAG_CORS_ORIGINS", "").split(",") if o.strip()]
if _cors:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

# base.d1an parsed columns, keyed by diag_path. Small (~18k rows x 5 f32 ~= 360 KB each).
_base_lru: "OrderedDict[str, dict]" = OrderedDict()
# Computed D1AN bytes, keyed by (diag_path, recipe_hash, layers_key). The common interaction
# — viewing several steps of one unchanged recipe — is then a single compute.
_result_lru: "OrderedDict[tuple, bytes]" = OrderedDict()


def _auth_headers(req: Request) -> dict:
    h: dict[str, str] = {}
    if "authorization" in req.headers:
        h["Authorization"] = req.headers["authorization"]
    if "cookie" in req.headers:
        h["Cookie"] = req.headers["cookie"]
    return h


async def _resolve_and_authorize(analysis_id: str, req: Request) -> dict:
    """Fetch diag_path + diag_status for `analysis_id` with the CALLER's credentials.

    Doubles as the authorization check: Directus applies the same row permissions it would
    for any read, so a caller who may not see the row gets its 403/401 here. Runs on every
    request — there is no cached bypass, matching filter-service's post-32fb4b7 behaviour.
    """
    async with httpx.AsyncClient(timeout=30) as cl:
        r = await cl.get(
            f"{DIRECTUS_URL}/items/machining_force_analysis/{analysis_id}",
            params={"fields": "diag_path,diag_status"},
            headers=_auth_headers(req),
        )
    if r.status_code in (401, 403):
        raise HTTPException(r.status_code, "not permitted")
    if r.status_code == 404:
        raise HTTPException(404, "analysis row not found")
    if r.status_code != 200:
        raise HTTPException(502, f"directus {r.status_code}")
    return (r.json() or {}).get("data") or {}


def _load_base(diag_path: str) -> dict:
    hit = _base_lru.get(diag_path)
    if hit is not None:
        _base_lru.move_to_end(diag_path)
        return hit
    path = os.path.join(OCTREE_ROOT, "diag", diag_path, "base.d1an")
    if not os.path.isfile(path):
        raise HTTPException(409, "no base.d1an for this analysis — rebake needed")
    cols = {k: np.asarray(v, dtype=np.float64) for k, v in read_d1an(path).items()}
    _base_lru[diag_path] = cols
    while len(_base_lru) > BASE_LRU_CAP:
        _base_lru.popitem(last=False)
    return cols


def _first_derived_index(recipe: dict) -> int:
    """The step to resume from: the first whose registry tier is 'derived'. Everything
    before it (frame_transform, angular_resample) is baked into base.d1an already."""
    for i, s in enumerate(recipe.get("steps", [])):
        spec = STEPS.get(s.get("op"))
        if spec is not None and spec.tier == "derived":
            return i
    raise HTTPException(422, "recipe has no derived step to preview")


@app.get("/health")
async def health():
    return {"ok": True, "base_lru": len(_base_lru), "result_lru": len(_result_lru)}


@app.post("/diag/preview")
async def preview(req: Request):
    body = await req.json()
    analysis_id = body.get("analysis_id")
    recipe = body.get("recipe")
    layers = body.get("layers") or None
    if not analysis_id or not isinstance(recipe, dict):
        raise HTTPException(422, "analysis_id and recipe are required")

    row = await _resolve_and_authorize(str(analysis_id), req)
    if row.get("diag_status") != "done" or not row.get("diag_path"):
        raise HTTPException(409, "analysis has no completed bake to preview from")
    diag_path = str(row["diag_path"])

    layers_key = repr(sorted((layers or {}).items())) if layers else ""
    key = (diag_path, recipe_hash(recipe), layers_key)
    cached = _result_lru.get(key)
    if cached is not None:
        _result_lru.move_to_end(key)
        return Response(cached, media_type="application/octet-stream",
                        headers={"Cache-Control": "no-store", "X-Diag-Cache": "hit"})

    base = _load_base(diag_path)
    t0 = time.perf_counter()
    try:
        cols, _metrics = run_recipe(
            recipe, dict(base), layers=layers, from_step=_first_derived_index(recipe)
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(422, f"recipe failed: {e}") from e

    with tempfile.NamedTemporaryFile(suffix=".d1an", delete=False) as f:
        tmp = f.name
    try:
        write_d1an(tmp, cols)
        out = open(tmp, "rb").read()
    finally:
        os.unlink(tmp)

    _result_lru[key] = out
    while len(_result_lru) > RESULT_LRU_CAP:
        _result_lru.popitem(last=False)
    return Response(out, media_type="application/octet-stream", headers={
        "Cache-Control": "no-store",
        "X-Diag-Cache": "miss",
        "X-Diag-Ms": f"{(time.perf_counter() - t0) * 1000:.0f}",
    })
```

- [ ] **Step 5: Run the tests**

Run: `py -m pytest plugins/diag-service/tests/test_preview.py -v`
Expected: PASS — 5 tests. If `test_preview_matches_a_full_bake` fails on a numeric mismatch, the resume path is not equivalent to a full run — investigate `_first_derived_index` and the `from_step` handoff, do not weaken the assertion.

- [ ] **Step 6: Lint**

Run: `py -m ruff check plugins/diag-service/`
Expected: clean. Fix anything it flags.

- [ ] **Step 7: Commit**

```bash
git add plugins/diag-service/
git commit -m "feat(diag): diag-service preview endpoint — re-run a recipe from base.d1an"
```

---

## Task 2: Deploy it — compose, Caddy, live end-to-end

**Files:**
- Create: `plugins/diag-service/Dockerfile`
- Modify: `docker-compose.yml` (after the `filter-service` block, ~line 311)
- Modify: `infra/caddy/Caddyfile` (after the `/filter/*` block, ~line 39)

**Interfaces:**
- Consumes: the app from Task 1.
- Produces: `diag-service` on the `d1net` network, port 8000 unpublished, reachable at `http://localhost/diag/*` through Caddy.

- [ ] **Step 1: Write the Dockerfile**

`plugins/diag-service/Dockerfile` (built from the repo root so it can reach `scripts/diag/`):

```dockerfile
# Build context is the REPO ROOT (see docker-compose.yml) so scripts/diag can be copied in
# verbatim — the service runs the identical recipe engine the orchestrator's bake uses.
FROM python:3.12-slim

WORKDIR /app

COPY plugins/diag-service/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/diag/ ./diag/
COPY plugins/diag-service/app/ ./app/
COPY plugins/diag-service/tests/ ./tests/

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=25s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Add the compose block**

In `docker-compose.yml`, immediately after the `filter-service` service block ends (before the next `#` service comment), add:

```yaml
  # diag-service: interactive diagnostics-recipe previews for the Diagnostics Workbench
  # (docs/superpowers/specs/2026-09-01-diagnostics-recipe-workbench-design.md, Component 4).
  # Re-runs a recipe from the published base.d1an using the SAME scripts/diag engine the
  # orchestrator's bake uses. Forwards the caller's Directus credentials for authz (no
  # service account). Served same-origin via Caddy at /diag/* — no published ports.
  diag-service:
    build:
      context: .
      dockerfile: plugins/diag-service/Dockerfile
    restart: unless-stopped
    depends_on:
      directus:
        condition: service_healthy
    environment:
      DIRECTUS_URL: http://directus:8055
      OCTREE_ROOT: /srv/octrees
      # CORS for the standalone Force App, which calls /diag/* cross-origin with a Bearer token.
      DIAG_CORS_ORIGINS: ${FORCE_APP_ORIGIN:-http://localhost:5180}
    volumes:
      - ./infra/octrees:/srv/octrees:ro   # read base.d1an off the same mount Caddy serves
    healthcheck:
      test:
        - "CMD"
        - "python"
        - "-c"
        - "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 25s
    networks: [d1net]
```

- [ ] **Step 3: Add the Caddy route**

In `infra/caddy/Caddyfile`, immediately after the `handle_path /filter/* { ... }` block, add:

```
    # diag-service (interactive diagnostics-recipe previews). Same-origin so the workbench can
    # call it under Directus's CSP; the service forwards the caller's Directus credentials when
    # resolving the analysis row, so authz stays Directus's. handle_path strips /diag,
    # mapping /diag/preview -> /diag/preview (the service also namespaces its route under /diag).
    handle_path /diag/* {
        reverse_proxy diag-service:8000
    }
```

Note: the service route is `POST /diag/preview` and Caddy `handle_path /diag/*` strips the `/diag` prefix, so the proxied path is `/preview`. Change the service route in `app/main.py` from `@app.post("/diag/preview")` to `@app.post("/preview")` **and** update the two test URLs in `test_preview.py` from `/diag/preview` to `/preview`. (The external URL stays `/diag/preview`; only the in-container path changes.) Re-run `py -m pytest plugins/diag-service/tests/ -v` to confirm still green.

- [ ] **Step 4: Validate compose and build**

Run: `docker compose config -q && echo OK`
Expected: `OK`

Run: `docker compose build diag-service 2>&1 | tail -5`
Expected: build succeeds.

- [ ] **Step 5: Bring it up and reload Caddy**

```bash
docker compose up -d diag-service
docker compose restart proxy
for i in $(seq 1 20); do s=$(docker inspect -f '{{.State.Health.Status}}' d1-database-diag-service-1 2>/dev/null); [ "$s" = healthy ] && break; sleep 3; done
echo "health: $s"
```

Expected: `health: healthy`.

- [ ] **Step 6: Live end-to-end against a real baked cut**

```bash
# ffe1286d has a completed bake with base.d1an (verified this session).
AID=$(docker exec d1-database-postgres-1 psql -U d1 -d d1_database -tAc \
  "select id from machining_force_analysis where operation_id='ffe1286d-b636-53b4-b8da-e8c3a6d07bba'")
echo "analysis id: $AID"

# Directus admin token for the forwarded-auth path.
TOKEN=$(curl -s -X POST http://localhost:8055/auth/login -H 'Content-Type: application/json' \
  -d "{\"email\":\"admin@example.com\",\"password\":\"$(grep DIRECTUS_ADMIN_PASSWORD .env | cut -d= -f2)\"}" \
  | python -c "import sys,json;print(json.load(sys.stdin)['data']['access_token'])")

RECIPE=$(py -c "import sys;sys.path.insert(0,'scripts');import json;from diag.recipe import DEFAULT_RECIPE;print(json.dumps(DEFAULT_RECIPE))")

curl -s -o /tmp/preview.d1an -w "%{http_code} %{size_download}b\n" \
  -X POST http://localhost/diag/preview \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"analysis_id\":\"$AID\",\"recipe\":$RECIPE,\"from_step\":null,\"layers\":null}"
```

Expected: `200 <N>b` with N > 100000 (11 columns × ~18k rows × 4 bytes ≈ 790 KB).

- [ ] **Step 7: Confirm the preview bytes match a local bake of the same op**

```bash
py -c "
import sys; sys.path.insert(0,'scripts')
from diag.d1an import read_d1an
import numpy as np
got = read_d1an('/tmp/preview.d1an')
print('columns:', sorted(got))
print('n:', got['t'].size, ' gi_sig nonzero:', int(np.count_nonzero(got['gi_sig'])))
assert set(got) == {'t','rev','x','y','tsa_resid','resid_z','gi_star','gi_sig','cluster_id','glosh','env_band'}
assert got['t'].size > 10000
print('OK')
"
```

Expected: `OK`, 11 columns, n ≈ 18148 (base.d1an's length — preview does not truncate; see the plan's note).

**Wait — resolve this before Step 7 passes:** `base.d1an` is the *pre-`tsa`* angular grid (~18148 rows), but `tsa` inside `run_recipe` truncates to whole revolutions (~17920). So the preview's public columns come back at the truncated length ~17920, not 18148. That is correct and matches a full bake's `attrs.d1an`. Update the Step 7 assertion to `got['t'].size == 17920` if the real op yields exactly that (check against `select diag_points from machining_force_analysis where operation_id='ffe1286d...'` — it was 17920 this session).

- [ ] **Step 8: Commit**

```bash
git add plugins/diag-service/Dockerfile docker-compose.yml infra/caddy/Caddyfile plugins/diag-service/app/main.py plugins/diag-service/tests/test_preview.py
git commit -m "feat(diag): deploy diag-service behind Caddy /diag/*"
```

---

## Self-Review

**Spec coverage.** Component 4 "Preview — diag-service": the container (Task 1+2), `POST /diag/preview` with `{analysis_id, recipe, from_step, layers}` (Task 1), forwarded-credential authorization including on cache hits (`_resolve_and_authorize` runs every request — Task 1), reads `base.d1an` (Task 1 `_load_base`), calls the same `run_recipe` (Task 1), Caddy `/diag/*` same-origin (Task 2). The `layers` parameter is accepted and passed through to `run_recipe` (which already accepts `layers=None`) — no layer *consumer* exists until Phase E, so this is a pass-through today.

**Deliberate deviations from the spec, and why:**
- The spec says the service "fetches `base.d1an` over Caddy". This plan reads it off the `./infra/octrees` bind mount instead — the identical bytes, one fewer network hop, and no dependency on the `proxy` container being up. Noted in `_load_base`'s path construction.
- The spec describes true *prefix* hashing (editing step 6 reuses the computed prefix through step 5). This plan caches on the *whole* recipe hash instead (`_result_lru` key includes `recipe_hash(recipe)`). For ~18k-row angular data the full derived chain is sub-second, so whole-recipe caching captures the dominant interaction (viewing multiple steps of one unchanged recipe) without the bookkeeping. True prefix caching is a deferred optimization to revisit with real Phase D latency numbers.
- `from_step` is accepted but does not change what is computed — the service always runs the full derived chain from `base.d1an` and returns all `PUBLIC_COLUMNS`. The client selects the channel to display. `from_step` is retained in the wire format for the future prefix-cache optimization.

**Type consistency.** `_resolve_and_authorize(analysis_id: str, req: Request) -> dict` is defined in Task 1 and monkeypatched by name in the tests. `run_recipe(recipe, cols, *, layers, from_step, ...)` matches `scripts/diag/runner.py`'s current signature. `read_d1an`/`write_d1an` take a path (str) — the service round-trips through a `NamedTemporaryFile` because those helpers are path-based; acceptable given the file is ~790 KB and deleted immediately.

**Not in scope (Phase D and later):** the TypeScript client (`fetchDiagPreview`), `ForceHost.diagUrl`, `apps/force-app/web/src/config.ts` `diagUrl` default, the `.env` `VITE_DIAG_URL`, and any UI. Phase D adds all of these when it wires the panel to this endpoint.
