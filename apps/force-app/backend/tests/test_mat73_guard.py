"""#194: a cut over MAT_MAX_BYTES used to get no .mat at all (MAT v5 cannot hold a > 2 GB variable),
so it uploaded with directus_files_id null and could not be baked. It now gets a MATLAB v7.3 (HDF5)
file with the same variables as the v5 one, written block by block.

MAT_MAX_BYTES is monkeypatched small so a tiny capture takes the long-cut path. There is no MATLAB
here, so the v7.3 layout MATLAB's `load` needs is checked point by point with h5py, and the content
is compared against the v5 file finalize writes for the same capture.
"""

import os
import shutil
import tracemalloc

import h5py
import numpy as np
import pytest
from scipy.io import loadmat

from app import finalize as finalize_mod
from app import mat73 as mat73_mod
from app.config import SIGNAL_CHANNELS, ExtraChannel, RecordConfig
from app.d1rw import RawWriter
from app.finalize import finalize

FS = 4000.0
N = 24_000


def _write_raw(path, n=N, extra_cols=0):
    os.makedirs(path, exist_ok=True)
    w = RawWriter(
        os.path.join(path, "raw.d1raw"),
        n_cols=1 + len(SIGNAL_CHANNELS) + extra_cols,
        rate=FS,
        start_unix=0.0,
    )
    idx = np.arange(n)
    data = np.zeros((n, len(SIGNAL_CHANNELS) + extra_cols))
    data[:, 0] = 10.0 + np.sin(idx / 50.0)  # Fx1
    data[:, 4] = np.where((idx > n // 4) & (idx < 3 * n // 4), 20.0, 0.5)  # Fz1: a cut window
    data[:, 8] = ((np.cumsum(np.full(n, 1200 / 60.0 / FS)) % 1.0) < 0.15) * 5.0  # tacho
    for i in range(extra_cols):
        data[:, 9 + i] = 99.0
    w.append(idx / FS, data)
    w.close()
    return path


def _cfg(**kw):
    return RecordConfig(
        sample_rate=FS,
        feed=0.05,
        diam=80,
        inner_diam=0,
        rpm=1200,
        ppr=1,
        sample_name="Ti-6Al-4V bar",
        extra_metadata={"op_type": "turning", "coolant": "flood", "note_number": 7},
        **kw,
    )


def _both(tmp_path, monkeypatch, n=N, extra_cols=0, **cfg_kw):
    """The same capture finalized under the limit (v5) and over it (v7.3)."""
    d5 = _write_raw(str(tmp_path / "v5"), n, extra_cols)
    d73 = str(tmp_path / "v73")
    os.makedirs(d73)
    shutil.copy(os.path.join(d5, "raw.d1raw"), d73)
    s5 = finalize(d5, _cfg(**cfg_kw))
    with monkeypatch.context() as m:
        m.setattr(finalize_mod, "MAT_MAX_BYTES", 1000)
        s73 = finalize(d73, _cfg(**cfg_kw))
    return d5, s5, d73, s73


def _text(ds) -> str:
    return "".join(chr(c) for c in np.asarray(ds[()]).ravel())


def test_a_normal_cut_is_still_a_v5_file(tmp_path, monkeypatch):
    d5, s5, _, _ = _both(tmp_path, monkeypatch)
    assert s5["mat_written"] is True
    assert s5["mat_format"] == "v5"
    assert s5["mat_skip_reason"] is None
    path = os.path.join(d5, "capture.mat")
    with open(path, "rb") as f:
        assert f.read(19) == b"MATLAB 5.0 MAT-file"
    assert loadmat(path)["DATA"].shape == (N, 10)  # scipy reads it: no behaviour change
    assert not os.path.exists(path + ".part")


def test_an_over_limit_cut_gets_a_v73_file(tmp_path, monkeypatch):
    _, _, d73, s73 = _both(tmp_path, monkeypatch)
    assert s73["mat_written"] is True
    assert s73["mat_format"] == "v7.3"
    assert s73["mat_skip_reason"] is None
    assert s73["files"]["mat"] == "capture.mat"
    assert "capture.mat" in s73["file_sizes_mb"]
    path = os.path.join(d73, "capture.mat")
    assert not os.path.exists(path + ".part")  # renamed into place only after a clean close
    with open(path, "rb") as f:
        head = f.read(512)
    assert head.startswith(b"MATLAB 7.3 MAT-file")
    assert head[124:128] == b"\x00\x02IM"  # version 0x0200, little-endian marker
    assert head[128:] == b"\x00" * 384 or head[128:].count(b"\x00") == 384
    assert h5py.is_hdf5(path)  # h5py finds the HDF5 signature after the userblock
    with h5py.File(path, "r") as f:
        assert f.userblock_size == 512
        assert set(f.keys()) == {"DATA", "metadata", "VariableNames", "#refs#"}


def test_v73_data_equals_the_v5_data(tmp_path, monkeypatch):
    d5, s5, d73, s73 = _both(tmp_path, monkeypatch)
    v5 = loadmat(os.path.join(d5, "capture.mat"))
    with h5py.File(os.path.join(d73, "capture.mat"), "r") as f:
        ds = f["DATA"]
        assert ds.shape == (10, N)  # MATLAB's N x 10, stored transposed
        assert ds.attrs["MATLAB_class"] == b"double"
        assert ds.dtype == np.dtype("<f8")
        np.testing.assert_array_equal(ds[()].T, v5["DATA"])
    assert s73["n"] == s5["n"] and s73["cut_window_sec"] == s5["cut_window_sec"]


def test_v73_with_extra_channels_equals_v5(tmp_path, monkeypatch):
    extra = [
        ExtraChannel(name="Temp", source="hardware", physical="cDAQ1Mod3/ai1"),
        ExtraChannel(name="Fz_twice", source="virtual", formula="2 * Fz"),
    ]
    d5, _, d73, s73 = _both(tmp_path, monkeypatch, extra_cols=1, extra_channels=extra)
    v5 = loadmat(os.path.join(d5, "capture.mat"))
    with h5py.File(os.path.join(d73, "capture.mat"), "r") as f:
        assert f["DATA"].shape == (12, N)
        np.testing.assert_array_equal(f["DATA"][()].T, v5["DATA"])
        names = [_text(f[r[0]]) for r in f["VariableNames"][()]]
    assert names == ["Time"] + SIGNAL_CHANNELS + ["Temp", "Fz_twice"]
    assert s73["channels"] == names


def test_v73_char_cell_and_struct_match_v5(tmp_path, monkeypatch):
    d5, _, d73, _ = _both(tmp_path, monkeypatch)
    v5 = loadmat(os.path.join(d5, "capture.mat"))
    with h5py.File(os.path.join(d73, "capture.mat"), "r") as f:
        # VariableNames: a 1xN cell of char -> (N, 1) object references into #refs#
        vn = f["VariableNames"]
        assert vn.attrs["MATLAB_class"] == b"cell"
        assert vn.shape == (10, 1) and vn.dtype == h5py.ref_dtype
        names = [_text(f[r[0]]) for r in vn[()]]
        assert names == [str(v[0]) for v in v5["VariableNames"].ravel()]
        for r in vn[()]:
            c = f[r[0]]
            assert c.attrs["MATLAB_class"] == b"char"
            assert c.dtype == np.uint16 and c.attrs["MATLAB_int_decode"] == 2
            assert c.parent.name == "/#refs#"

        # metadata: a 1x1 struct -> group, MATLAB_class struct, one child per field, same order
        md = f["metadata"]
        assert isinstance(md, h5py.Group) and md.attrs["MATLAB_class"] == b"struct"
        fields = ["".join(c.astype(str)) for c in md.attrs["MATLAB_fields"]]
        assert fields == list(v5["metadata"].dtype.names)
        assert set(md.keys()) == set(fields)
        for name in fields:
            want = v5["metadata"][name][0, 0]
            got = md[name]
            if want.dtype.kind == "U":  # char
                assert got.attrs["MATLAB_class"] == b"char"
                assert _text(got) == str(want[0])
            else:  # numeric scalar: 1x1, same class as scipy wrote
                assert got.shape == (1, 1)
                assert got[0, 0] == want.ravel()[0], name
                cls = {"f": b"double", "i": b"int", "u": b"uint"}[want.dtype.kind]
                assert got.attrs["MATLAB_class"].startswith(cls), name
        assert _text(md["SampleName"]) == "Ti-6Al-4V bar"
        assert md["Rate"][0, 0] == FS and md["fileVersion"][0, 0] == 1.0
        assert _text(md["op_type"]) == "turning"


def test_the_writer_encodes_each_matlab_type(tmp_path):
    p = str(tmp_path / "t.mat")
    with mat73_mod.Mat73Writer(p) as w:
        w.write_variable(
            "s", {"txt": "é€", "empty": "", "n": 3, "flag": True, "x": 1.5, "none": None}
        )
        w.write_variable("v", np.array([1.0, 2.0, 3.0], dtype=np.float32))
    with h5py.File(p, "r") as f:
        s = f["s"]
        assert _text(s["txt"]) == "é€" and s["txt"].shape == (2, 1)
        assert s["empty"].attrs["MATLAB_empty"] == 1 and s["empty"].attrs["MATLAB_class"] == b"char"
        assert s["n"].attrs["MATLAB_class"] == b"int64" and s["n"].shape == (1, 1)
        assert s["flag"].attrs["MATLAB_class"] == b"logical" and s["flag"].dtype == np.uint8
        assert s["x"][0, 0] == 1.5 and s["x"].attrs["MATLAB_class"] == b"double"
        assert "none" not in s  # None is skipped, as v5 does
        assert f["v"].shape == (3, 1) and f["v"].attrs["MATLAB_class"] == b"single"
    with open(p, "rb") as fh:
        assert fh.read(19) == b"MATLAB 7.3 MAT-file"


def test_the_v73_file_is_streamed_block_by_block(tmp_path, monkeypatch):
    # With 1,000-row blocks the 24,000-row capture is written in 24 block writes of DATA, never as
    # one array, and the dataset is chunked along time in divisors of the block.
    monkeypatch.setattr(finalize_mod, "BLOCK_ROWS", 1_000)
    calls = []
    real = mat73_mod.Mat73Writer.write_rows

    def spy(self, start, block):
        calls.append((start, block.shape))
        return real(self, start, block)

    monkeypatch.setattr(mat73_mod.Mat73Writer, "write_rows", spy)
    d5, _, d73, _ = _both(tmp_path, monkeypatch)
    assert [c[0] for c in calls] == list(range(0, N, 1_000))
    assert all(shape == (1_000, 10) for _, shape in calls)
    with h5py.File(os.path.join(d73, "capture.mat"), "r") as f:
        assert f["DATA"].chunks == (10, 1_000)
        assert f["DATA"].compression == "gzip"
        np.testing.assert_array_equal(
            f["DATA"][()].T, loadmat(os.path.join(d5, "capture.mat"))["DATA"]
        )


def test_v73_memory_is_bounded_by_the_block_not_the_capture(tmp_path, monkeypatch):
    n = 2_000_000  # DATA is 160 MB; one 50,000-row block is 4 MB
    monkeypatch.setattr(finalize_mod, "BLOCK_ROWS", 50_000)
    monkeypatch.setattr(finalize_mod, "MAT_MAX_BYTES", 1000)
    d = _write_raw(str(tmp_path / "long"), n)
    tracemalloc.start()
    try:
        summary = finalize(d, _cfg())
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert summary["mat_format"] == "v7.3"
    full_data = n * 10 * 8
    assert peak < full_data / 3, f"peak {peak / 1e6:.1f} MB for {full_data / 1e6:.0f} MB of DATA"


def test_v73_needs_free_disk_and_otherwise_writes_no_mat(tmp_path, monkeypatch):
    monkeypatch.setattr(finalize_mod, "MAT_MAX_BYTES", 1000)
    monkeypatch.setattr(finalize_mod, "_free_bytes", lambda path: 1_000)
    d = _write_raw(str(tmp_path / "full"))
    summary = finalize(d, _cfg())
    assert summary["mat_written"] is False
    assert summary["mat_format"] is None
    assert "v7.3" in summary["mat_skip_reason"] and "free" in summary["mat_skip_reason"]
    assert summary["files"]["mat"] is None
    assert not os.path.exists(os.path.join(d, "capture.mat"))
    assert os.path.isfile(os.path.join(d, "live_cache.bin"))  # the rest is still produced


def test_a_failed_v73_write_drops_the_mat_but_not_the_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(finalize_mod, "MAT_MAX_BYTES", 1000)

    def boom(self, start, block):
        raise OSError("No space left on device")

    monkeypatch.setattr(mat73_mod.Mat73Writer, "write_rows", boom)
    d = _write_raw(str(tmp_path / "fail"))
    summary = finalize(d, _cfg())
    assert summary["mat_written"] is False and summary["mat_format"] is None
    assert "No space left" in summary["mat_skip_reason"]
    assert sorted(os.listdir(d)) == ["live_cache.bin", "raw.d1raw", "summary.json"]  # no .part left
    assert summary["n"] == N


def test_disk_check_helper_counts_the_uncompressed_size():
    need = mat73_mod.mat73_disk_need(100_000_000, 10)  # 8 GB of DATA
    assert 8.0e9 < need < 8.6e9


@pytest.mark.parametrize("limit", [10**12])
def test_a_huge_limit_keeps_v5(tmp_path, monkeypatch, limit):
    monkeypatch.setattr(finalize_mod, "MAT_MAX_BYTES", limit)
    d = _write_raw(str(tmp_path / "x"))
    assert finalize(d, _cfg())["mat_format"] == "v5"
