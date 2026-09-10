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
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from diag.d1an import read_d1an, write_d1an  # noqa: E402


def _read(buf: bytes) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".d1an", delete=False) as f:
        f.write(buf)
        path = f.name
    try:
        return read_d1an(path)
    finally:
        os.unlink(path)


@pytest.fixture
def client(tmp_path, monkeypatch):
    full = tmp_path / "octrees" / "diag" / "op-under-test" / "full"
    full.mkdir(parents=True)
    rng = np.random.default_rng(0)
    n = 40_000
    x = rng.uniform(-40, 40, n).astype(np.float32)
    y = rng.uniform(-40, 40, n).astype(np.float32)
    rz = rng.normal(0, 1, n).astype(np.float32)
    rz[(x > 10) & (x < 20)] += 6.0
    write_d1an(str(full / "full.d1an"), {"x": x, "y": y, "resid_z": rz})
    monkeypatch.setenv("OCTREE_ROOT", str(tmp_path / "octrees"))

    import app.main as m

    m._base_lru.clear()
    m._result_lru.clear()
    if hasattr(m, "_full_lru"):
        m._full_lru.clear()
    if hasattr(m, "_viewport_lru"):
        m._viewport_lru.clear()

    async def _allow(analysis_id, req):
        return {"diag_path": "op-under-test", "diag_status": "done"}

    monkeypatch.setattr(m, "_resolve_and_authorize", _allow)

    from fastapi.testclient import TestClient

    return TestClient(m.app)


def test_viewport_crops_to_the_bbox(client):
    r = client.post(
        "/viewport",
        json={
            "analysis_id": "a1",
            "bbox": [0, -40, 40, 40],
            "step": {"op": "getis_ord", "params": {"k": 20}},
        },
    )
    assert r.status_code == 200, r.text
    got = _read(r.content)
    assert np.all(got["x"] >= 0) and np.all(got["x"] <= 40)
    assert "value" in got
    assert int(r.headers["x-diag-viewport-n"]) == got["x"].size


def test_viewport_strides_over_max_points(client):
    r = client.post(
        "/viewport",
        json={
            "analysis_id": "a1",
            "bbox": [-40, -40, 40, 40],
            "step": {"op": "getis_ord", "params": {"k": 10}},
            "max_points": 5000,
        },
    )
    assert r.status_code == 200
    assert _read(r.content)["x"].size <= 5000


def test_viewport_hdbscan_returns_cluster_id(client):
    r = client.post(
        "/viewport",
        json={
            "analysis_id": "a1",
            "bbox": [-40, -40, 40, 40],
            "step": {"op": "hdbscan", "params": {"min_cluster_size": 20}},
        },
    )
    assert r.status_code == 200
    v = _read(r.content)["value"]
    assert set(np.unique(v)) - {-1.0}  # at least one real cluster


def test_viewport_gmm_segmentation_returns_gmm_id(client):
    r = client.post(
        "/viewport",
        json={
            "analysis_id": "a1",
            "bbox": [-40, -40, 40, 40],
            "step": {
                "op": "gmm_segmentation",
                "params": {"n_components": 3, "random_state": 0, "grid_target": 500},
            },
        },
    )
    assert r.status_code == 200, r.text
    v = _read(r.content)["value"]
    # Unlike HDBSCAN, GMM assigns every point -- no -1 noise class.
    assert set(np.unique(v)) <= {0.0, 1.0, 2.0}
    assert -1.0 not in set(np.unique(v))


def test_viewport_outputs_returns_one_named_column_per_request(client):
    # gmm_id + gmm_prob together in one response, the case griddify-style value+confidence
    # steps need: the client wants to colour by one and modulate opacity by the other.
    r = client.post(
        "/viewport",
        json={
            "analysis_id": "a1",
            "bbox": [-40, -40, 40, 40],
            "step": {
                "op": "gmm_segmentation",
                "params": {"n_components": 3, "random_state": 0, "grid_target": 500},
            },
            "outputs": ["gmm_id", "gmm_prob"],
        },
    )
    assert r.status_code == 200, r.text
    assert r.headers["x-diag-viewport-cols"] == "gmm_id,gmm_prob"
    cols = _read(r.content)
    assert set(cols) == {"x", "y", "gmm_id", "gmm_prob"}
    assert set(np.unique(cols["gmm_id"])) <= {0.0, 1.0, 2.0}
    assert np.all(cols["gmm_prob"] >= 0.0) and np.all(cols["gmm_prob"] <= 1.0 + 1e-6)


def test_viewport_outputs_rejects_a_column_the_op_does_not_produce(client):
    r = client.post(
        "/viewport",
        json={
            "analysis_id": "a1",
            "bbox": [-40, -40, 40, 40],
            "step": {"op": "hdbscan", "params": {"min_cluster_size": 20}},
            "outputs": ["cluster_id", "gmm_prob"],
        },
    )
    assert r.status_code == 422
    assert "gmm_prob" in r.text


def test_viewport_outputs_rejects_an_empty_list(client):
    r = client.post(
        "/viewport",
        json={
            "analysis_id": "a1",
            "bbox": [-40, -40, 40, 40],
            "step": {"op": "hdbscan", "params": {}},
            "outputs": [],
        },
    )
    assert r.status_code == 422


def test_viewport_without_outputs_still_returns_the_legacy_single_value_column(client):
    # Byte-for-byte the pre-widening contract: 'value', not the op's real column name.
    r = client.post(
        "/viewport",
        json={
            "analysis_id": "a1",
            "bbox": [-40, -40, 40, 40],
            "step": {"op": "hdbscan", "params": {"min_cluster_size": 20}},
        },
    )
    assert r.status_code == 200
    assert r.headers["x-diag-viewport-cols"] == "value"
    assert set(_read(r.content)) == {"x", "y", "value"}


def test_viewport_outputs_cache_hit_reproduces_the_cols_header(client):
    body = {
        "analysis_id": "a1",
        "bbox": [-40, -40, 40, 40],
        "step": {
            "op": "gmm_segmentation",
            "params": {"n_components": 3, "random_state": 0, "grid_target": 500},
        },
        "outputs": ["gmm_id", "gmm_prob"],
    }
    first = client.post("/viewport", json=body)
    assert first.headers["x-diag-cache"] == "miss"
    second = client.post("/viewport", json=body)
    assert second.headers["x-diag-cache"] == "hit"
    assert second.headers["x-diag-viewport-cols"] == "gmm_id,gmm_prob"
    assert second.content == first.content


def test_viewport_segmentation_two_seed_polys(client):
    left = [[[-1e6, -1e6], [-5, -1e6], [-5, 1e6], [-1e6, 1e6]]]
    right = [[[5, -1e6], [1e6, -1e6], [1e6, 1e6], [5, 1e6]]]
    r = client.post(
        "/viewport",
        json={
            "analysis_id": "a1",
            "bbox": [-40, -40, 40, 40],
            "step": {
                "op": "grow_segmentation",
                "params": {"features": ["resid_z"]},
                "inputs": {"seeds": {"layers": ["L", "R"]}},
            },
            "layers": {
                "L": {"role": "seed", "geometry": {"polygons": left}, "value": None, "version": 1},
                "R": {"role": "seed", "geometry": {"polygons": right}, "value": None, "version": 1},
            },
        },
    )
    assert r.status_code == 200, r.text
    assert set(np.unique(_read(r.content)["value"])) <= {0.0, 1.0}


def test_viewport_segmentation_required_seed_missing_is_422_not_500(client):
    """grow_segmentation's inputs binding requires a seed layer that isn't in the request's
    `layers` dict. resolve_inputs raises RecipeError (a ValueError subclass) -- and it runs
    OUTSIDE the endpoint's step-call try/except unless moved in, so it used to surface as an
    unhandled 500 instead of the 422 contract every other failure path here follows."""
    r = client.post(
        "/viewport",
        json={
            "analysis_id": "a1",
            "bbox": [-40, -40, 40, 40],
            "step": {
                "op": "grow_segmentation",
                "params": {"features": ["resid_z"]},
                "inputs": {"seeds": {"layers": ["does-not-exist"], "required": True}},
            },
            "layers": {},
        },
    )
    assert r.status_code == 422, r.text


def test_viewport_applies_a_mask_layer_to_gi_star(client):
    """A mask painted after the last bake is not in full.d1an's NaN pattern; the endpoint
    must rasterise mask-role layers onto the crop so Gi* skips the excluded region."""
    box = [[[-5.0, -5.0], [5.0, -5.0], [5.0, 5.0], [-5.0, 5.0]]]
    r = client.post(
        "/viewport",
        json={
            "analysis_id": "a1",
            "bbox": [-40, -40, 40, 40],
            "step": {"op": "getis_ord", "params": {"k": 20}},
            "layers": {
                "chuck": {"role": "mask", "geometry": {"polygons": box}, "value": None, "version": 1},
            },
        },
    )
    assert r.status_code == 200, r.text
    got = _read(r.content)
    inside = (np.abs(got["x"]) <= 5) & (np.abs(got["y"]) <= 5)
    assert inside.any()
    assert np.all(np.isnan(got["value"][inside]))          # masked -> excluded from Gi*
    assert np.isfinite(got["value"][~inside]).any()        # the rest still computed


def test_viewport_rejects_a_bad_max_points(client):
    for mp in (-5, 0):
        r = client.post(
            "/viewport",
            json={
                "analysis_id": "a1", "bbox": [-40, -40, 40, 40],
                "step": {"op": "getis_ord", "params": {}}, "max_points": mp,
            },
        )
        assert r.status_code == 422, (mp, r.text)


def test_viewport_rejects_a_non_numeric_bbox(client):
    r = client.post(
        "/viewport",
        json={
            "analysis_id": "a1", "bbox": [None, 0, 1, 1],
            "step": {"op": "getis_ord", "params": {}},
        },
    )
    assert r.status_code == 422


def test_viewport_rejects_a_non_spatial_step(client):
    r = client.post(
        "/viewport",
        json={
            "analysis_id": "a1",
            "bbox": [-40, -40, 40, 40],
            "step": {"op": "tsa", "params": {}},
        },
    )
    assert r.status_code == 422


def test_viewport_empty_bbox_is_422(client):
    r = client.post(
        "/viewport",
        json={
            "analysis_id": "a1",
            "bbox": [1000, 1000, 1001, 1001],
            "step": {"op": "getis_ord", "params": {}},
        },
    )
    assert r.status_code == 422


def test_viewport_authorizes_on_lru_hit(client, monkeypatch):
    body = {
        "analysis_id": "a1",
        "bbox": [-40, -40, 40, 40],
        "step": {"op": "getis_ord", "params": {"k": 10}},
    }
    assert client.post("/viewport", json=body).status_code == 200  # populates LRU
    import app.main as m

    async def _deny(analysis_id, req):
        from fastapi import HTTPException

        raise HTTPException(403, "nope")

    monkeypatch.setattr(m, "_resolve_and_authorize", _deny)
    assert client.post("/viewport", json=body).status_code == 403  # hit still re-checks
