import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag import d1an


def test_round_trip_preserves_columns(tmp_path):
    cols = {
        "t": np.linspace(0.0, 1.0, 64, dtype=np.float32),
        "resid_z": np.random.default_rng(0).normal(size=64).astype(np.float32),
    }
    p = str(tmp_path / "a.d1an")
    d1an.write_d1an(p, cols)
    back = d1an.read_d1an(p)
    assert set(back) == {"t", "resid_z"}
    for k in cols:
        np.testing.assert_allclose(back[k], cols[k], rtol=0, atol=0)


def test_rejects_ragged_columns(tmp_path):
    cols = {"a": np.zeros(4, np.float32), "b": np.zeros(5, np.float32)}
    with pytest.raises(ValueError, match="same length"):
        d1an.write_d1an(str(tmp_path / "b.d1an"), cols)


def test_rejects_bad_magic(tmp_path):
    p = tmp_path / "bad.d1an"
    p.write_bytes(b"\x00" * 32)
    with pytest.raises(ValueError, match="magic"):
        d1an.read_d1an(str(p))


def test_rejects_overlong_column_name(tmp_path):
    cols = {"x" * 17: np.zeros(4, np.float32)}
    with pytest.raises(ValueError, match="name"):
        d1an.write_d1an(str(tmp_path / "c.d1an"), cols)
