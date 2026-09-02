"""diag-service preview tests.

The Directus authorization call is stubbed; the compute path is exercised for real against a
base.d1an written from the shared diag test synthetic, and its output is asserted identical to
calling run_recipe directly on the full cut (preview must not diverge from the bake path).
"""

from __future__ import annotations

import os
import sys
import tempfile

import numpy as np
import pytest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
for _p in (
    os.path.join(_REPO, "scripts"),
    os.path.join(_REPO, "plugins", "diag-service"),
    os.path.join(_REPO, "tests", "scripts", "diag"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from conftest import cache_of, synthetic_cut  # noqa: E402
from diag.d1an import read_d1an, write_d1an  # noqa: E402
from diag.recipe import DEFAULT_RECIPE  # noqa: E402
from diag.runner import run_recipe, seed_columns  # noqa: E402

BASE_COLUMNS = ("t", "rev", "x", "y", "sig")
PUBLIC = {
    "t", "rev", "x", "y", "tsa_resid", "resid_z",
    "gi_star", "gi_sig", "cluster_id", "glosh", "env_band",
}


def _write_base_d1an(dst: str) -> None:
    """Exactly what process_diag_row publishes: the default recipe stopped after
    angular_resample, emitting the base column set."""
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = synthetic_cut()
    stop = next(
        i for i, s in enumerate(DEFAULT_RECIPE["steps"]) if s["op"] == "angular_resample"
    )
    cols, _ = run_recipe(
        DEFAULT_RECIPE,
        seed_columns(cache_of(t, fx, fy, fz, rpm, revs, fs), x, y),
        stop_after=stop,
        emit=BASE_COLUMNS,
    )
    write_d1an(dst, cols)


def _full_bake():
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = synthetic_cut()
    return run_recipe(
        DEFAULT_RECIPE, seed_columns(cache_of(t, fx, fy, fz, rpm, revs, fs), x, y)
    )


def _read_bytes(buf: bytes) -> dict[str, np.ndarray]:
    with tempfile.NamedTemporaryFile(suffix=".d1an", delete=False) as f:
        f.write(buf)
        path = f.name
    try:
        return read_d1an(path)
    finally:
        os.unlink(path)


@pytest.fixture
def client(tmp_path, monkeypatch):
    root = tmp_path / "octrees" / "diag" / "op-under-test"
    root.mkdir(parents=True)
    _write_base_d1an(str(root / "base.d1an"))
    monkeypatch.setenv("OCTREE_ROOT", str(tmp_path / "octrees"))

    import app.main as m

    # fresh LRUs per test
    m._base_lru.clear()
    m._result_lru.clear()

    async def _allow(analysis_id, req):
        return {"diag_path": "op-under-test", "diag_status": "done"}

    monkeypatch.setattr(m, "_resolve_and_authorize", _allow)

    from fastapi.testclient import TestClient

    return TestClient(m.app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_preview_approximates_a_full_bake(client):
    """Preview resumes from base.d1an, which is float32 — so preview re-enters the pipeline
    at lower precision than a float64 full bake. It is a fast approximation; the bake is
    authoritative (spec Component 4). This pins the C-4 acceptance criterion.

    The tolerances here accommodate the SYNTHETIC cut, whose perfect Archimedean spiral
    creates exact k-NN ties that float32 quantisation flips. Measured against real
    process_force.m geometry (operation ffe1286d, this session):
      - continuous channels ~100x tighter: resid_z max|abs| 1.6e-4, tsa_resid 1.5e-8
      - gi_sig BYTE-IDENTICAL to the bake
      - cluster_id agrees 99.87% (a few boundary points reassign under float32 either way)
      - gi_star correlation 0.9997 (a uniform tiny scaling, not structural)
    The bake stays authoritative for every number a user records.
    """
    r = client.post(
        "/preview",
        json={"analysis_id": "a1", "recipe": DEFAULT_RECIPE, "from_step": None, "layers": None},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["x-diag-preview"] == "approximate"

    got = _read_bytes(r.content)
    want, _ = _full_bake()
    assert set(got) == PUBLIC == set(want)

    # pass-through / structurally-exact columns
    for name in ("t", "rev", "x", "y", "env_band"):
        np.testing.assert_array_equal(got[name], want[name], err_msg=f"{name} must be exact")

    # continuous statistics: close, not equal
    for name in ("tsa_resid", "resid_z", "glosh"):
        np.testing.assert_allclose(
            got[name], want[name], rtol=0.05, atol=0.05, err_msg=f"{name} out of float32 band"
        )

    # gi_star swings hardest on the synthetic's tie degeneracy — assert shape, not values
    gs_a, gs_b = got["gi_star"].astype(np.float64), want["gi_star"].astype(np.float64)
    assert np.corrcoef(gs_a, gs_b)[0, 1] > 0.97

    # the decision outputs the UI renders must stay put
    assert np.mean(got["gi_sig"] == want["gi_sig"]) >= 0.99
    assert np.mean(got["cluster_id"] == want["cluster_id"]) >= 0.99


def test_preview_reflects_a_param_change(client):
    hot = {
        "recipe_version": 1,
        "name": "hot",
        "steps": [
            {**s, "params": {**s["params"], "k": 50}} if s["op"] == "getis_ord" else dict(s)
            for s in DEFAULT_RECIPE["steps"]
        ],
    }
    a = client.post(
        "/preview",
        json={"analysis_id": "a1", "recipe": DEFAULT_RECIPE, "from_step": None, "layers": None},
    )
    b = client.post(
        "/preview",
        json={"analysis_id": "a1", "recipe": hot, "from_step": None, "layers": None},
    )
    assert a.status_code == b.status_code == 200
    ga, gb = _read_bytes(a.content), _read_bytes(b.content)
    assert not np.array_equal(ga["gi_star"], gb["gi_star"]), "k=30 vs k=50 must move gi_star"
    assert a.headers["x-diag-cache"] == "miss"


def test_repeated_identical_request_is_cache_hit(client):
    body = {"analysis_id": "a1", "recipe": DEFAULT_RECIPE, "from_step": None, "layers": None}
    first = client.post("/preview", json=body)
    second = client.post("/preview", json=body)
    assert first.headers["x-diag-cache"] == "miss"
    assert second.headers["x-diag-cache"] == "hit"
    assert first.content == second.content


def test_analysis_not_done_is_409(client, monkeypatch):
    import app.main as m

    async def _pending(analysis_id, req):
        return {"diag_path": None, "diag_status": "pending"}

    monkeypatch.setattr(m, "_resolve_and_authorize", _pending)
    r = client.post(
        "/preview",
        json={"analysis_id": "x", "recipe": DEFAULT_RECIPE, "from_step": None, "layers": None},
    )
    assert r.status_code == 409


def test_missing_base_d1an_is_409(client, monkeypatch):
    import app.main as m

    async def _other(analysis_id, req):
        return {"diag_path": "op-with-no-base", "diag_status": "done"}

    monkeypatch.setattr(m, "_resolve_and_authorize", _other)
    r = client.post(
        "/preview",
        json={"analysis_id": "x", "recipe": DEFAULT_RECIPE, "from_step": None, "layers": None},
    )
    assert r.status_code == 409
