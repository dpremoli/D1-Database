"""Official-crop opts and the d1_build.json manifest in the octree/grid builds.

MATLAB, PotreeConverter, laspy and the database are all stubbed: these tests pin what the
orchestrator asks MATLAB for and what it publishes, not the MATLAB numerics.
"""

import json
import os
import re
import struct
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

pytest.importorskip("psycopg2")
pytest.importorskip("requests")
np = pytest.importorskip("numpy")

import force_orchestrator as fo  # noqa: E402

MATLAB_JSON = {
    "feed": 0.05,
    "diam": 80.0,
    "inner_diam": 0.0,
    "ppr": 1,
    "cut_start_sec": 0.264,
    "cut_end_sec": 3.867,
    "crop_source": "override",
    "speed_mode": "measured",
}
CONTRACT_KEYS = {
    "schema",
    "kind",
    "speed_mode",
    "feed",
    "diam",
    "inner_diam",
    "ppr",
    "cut_start_sec",
    "cut_end_sec",
    "crop_source",
    "n_points",
    "built_at",
}


class FakeConn:
    """Records executed SQL; fetchall returns no rows."""

    def __init__(self):
        self.sql = []

    def cursor(self, **_kw):
        conn = self

        class Cur:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params=None):
                conn.sql.append(sql)

            def fetchall(self):
                return []

        return Cur()

    def commit(self):
        pass

    def rollback(self):
        pass


def _row(**kw):
    r = {
        "id": "a1",
        "operation_id": "op-1",
        "archive_path": "x/y/10-AA-1.mat",
        "pulses_per_rev": None,
        "inner_diameter": None,
        "outer_diameter": None,
        "filter_chain": None,
        "sample_rate": 25600,
        "crop_start_idx_override": None,
        "crop_end_idx_override": None,
    }
    r.update(kw)
    return r


def _write_bin(path: str, grid: bool):
    n = 3
    with open(path, "wb") as f:
        if grid:
            f.write(struct.pack("<IIfff", 0x44314752, n, 0.9, 2.0, 0.1))
        else:
            f.write(struct.pack("<II", 0x44314F43, n))
        f.write(np.arange(n * 5, dtype="<f4").tobytes())


@pytest.fixture
def stubbed(tmp_path, monkeypatch):
    """Stub subprocess/laspy/unc_for; records the MATLAB statements."""
    env = SimpleNamespace(
        stmts=[],
        matlab_json=dict(MATLAB_JSON),
        matlab_json_text=None,
        out=tmp_path / "pub",
    )
    monkeypatch.setattr(fo, "OCTREE_DIR", env.out)
    monkeypatch.setattr(fo, "unc_for", lambda p: "/unc/" + p)
    monkeypatch.setenv("FORCE_WORKDIR", str(tmp_path))
    monkeypatch.setitem(sys.modules, "laspy", MagicMock())

    def fake_run(cmd, **_kw):
        if cmd[0] == "matlab":
            stmt = cmd[2]
            env.stmts.append(stmt)
            m = re.search(r"'(octree_out|grid_out)','([^']+)'", stmt)
            binp = m.group(2)
            _write_bin(binp, m.group(1) == "grid_out")
            if env.matlab_json_text is not None:
                Path(binp + ".json").write_text(env.matlab_json_text)
            elif env.matlab_json is not None:
                Path(binp + ".json").write_text(json.dumps(env.matlab_json))
        else:  # PotreeConverter: <las> -o <dir>
            out = Path(cmd[cmd.index("-o") + 1])
            out.mkdir(parents=True)
            (out / "metadata.json").write_text('{"attributes": []}')
            (out / "hierarchy.bin").write_bytes(b"h")
            (out / "octree.bin").write_bytes(b"o")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fo.subprocess, "run", fake_run)
    return env


def _octree(env, **row):
    return fo.process_octree_row(
        FakeConn(), _row(**row), "matlab", 60, {"series_points": 3000}, "potree"
    )


def _grid(env, **row):
    grid_opts = {"n": 128, "method": "splat", "cv_arm_step": 10}
    return fo.process_grid_row(
        FakeConn(),
        _row(**row),
        "matlab",
        60,
        {"series_points": 3000},
        grid_opts,
        "potree",
    )


def test_claims_select_crop_columns():
    for claim in (fo.claim_octree, fo.claim_grid):
        conn = FakeConn()
        claim(conn)
        for col in (
            "crop_start_idx_override",
            "crop_end_idx_override",
            "a.sample_rate",
        ):
            assert col in conn.sql[0]


def test_crop_opts_only_when_set():
    assert fo._crop_opts(_row()) == {}
    assert fo._crop_opts(_row(crop_start_idx_override=6758)) == {
        "crop_start_sec": 6758 / 25600
    }
    both = fo._crop_opts(_row(crop_start_idx_override=0, crop_end_idx_override=99000))
    assert both == {"crop_start_sec": 0.0, "crop_end_sec": 99000 / 25600}


@pytest.mark.parametrize("fs", [None, 0, -1])
def test_crop_opts_need_a_sample_rate(fs):
    assert fo._crop_opts(_row(sample_rate=fs, crop_start_idx_override=100)) == {}


def test_crop_round_trip():
    fs, sec = 25600, 0.264
    idx = round(sec * fs)  # what the dashboard stores
    got = fo._crop_opts(_row(crop_start_idx_override=idx))["crop_start_sec"]
    assert got == pytest.approx(sec, abs=0.5 / fs)


@pytest.mark.parametrize("build", [_octree, _grid])
def test_builds_pass_crop_only_when_set(stubbed, build):
    assert build(stubbed) == "done"
    assert "crop_start_sec" not in stubbed.stmts[-1]
    assert "crop_end_sec" not in stubbed.stmts[-1]
    assert (
        build(stubbed, crop_start_idx_override=25600, crop_end_idx_override=51200)
        == "done"
    )
    assert "'crop_start_sec',1.0" in stubbed.stmts[-1]
    assert "'crop_end_sec',2.0" in stubbed.stmts[-1]


@pytest.mark.parametrize(
    ("build", "kind", "sub"),
    [(_octree, "octree", "op-1"), (_grid, "grid", "grid/op-1")],
)
def test_manifest_published_with_contract_keys(stubbed, build, kind, sub):
    assert build(stubbed) == "done"
    m = json.loads((stubbed.out / sub / "d1_build.json").read_text())
    assert set(m) == CONTRACT_KEYS
    assert (m["schema"], m["kind"], m["n_points"]) == (1, kind, 3)
    for k, v in MATLAB_JSON.items():
        assert m[k] == v
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", m["built_at"])
    assert (stubbed.out / sub / "metadata.json").exists()


@pytest.mark.parametrize("build", [_octree, _grid])
@pytest.mark.parametrize("case", ["missing", "malformed", "incomplete"])
def test_missing_or_bad_matlab_json_publishes_no_manifest(stubbed, build, case, caplog):
    if case == "missing":
        stubbed.matlab_json = None
    elif case == "malformed":
        stubbed.matlab_json_text = "not json"
    else:
        stubbed.matlab_json = {"feed": 1}
    assert build(stubbed) == "done"  # a missing manifest never fails the build
    assert not list(stubbed.out.rglob("d1_build.json"))
    assert list(stubbed.out.rglob("metadata.json"))
    assert any("d1_build.json" in r.getMessage() for r in caplog.records)


def test_process_file_never_carries_crop_keys(monkeypatch):
    seen = {}

    def fake_run_matlab(exe, unc, outdir, timeout, matlab_opts):
        seen.update(matlab_opts)
        return False, "stop"

    monkeypatch.setattr(fo, "run_matlab", fake_run_matlab)
    monkeypatch.setattr(fo, "unc_for", lambda p: p)
    row = _row(
        crop_start_idx_override=100, crop_end_idx_override=900, live_render_points=5
    )
    res = fo.process_file(row, "matlab", 60, {"series_points": 3000})
    fo.shutil.rmtree(res["outdir"], ignore_errors=True)
    assert seen["series_points"] == 3000
    assert not {"crop_start_sec", "crop_end_sec"} & set(seen)
