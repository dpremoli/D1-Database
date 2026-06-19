"""Unit tests for the D1F parser and streaming stats."""

import pytest

from app.lib.parser import parse_header, strided_read
from app.lib.stats import streaming_stats
from tests.generate_test_file import HEADER_SIZE, N_CHANNELS, write_d1f


@pytest.fixture(scope="module")
def tiny_d1f(tmp_path_factory):
    path = tmp_path_factory.mktemp("data") / "test.d1f"
    write_d1f(str(path), n_samples=10_000, sample_rate_hz=10_000.0)
    return path


# ---- header parsing ----


def test_parse_header(tiny_d1f):
    with open(tiny_d1f, "rb") as f:
        h = parse_header(f)
    assert h["n_channels"] == N_CHANNELS
    assert h["n_samples"] == 10_000
    assert h["sample_rate_hz"] == pytest.approx(10_000.0)
    assert h["version"] == 1


def test_bad_magic(tmp_path):
    p = tmp_path / "bad.d1f"
    p.write_bytes(b"BADMAGIC" + b"\x00" * 56)
    with open(p, "rb") as f:
        with pytest.raises(ValueError, match="Not a D1F file"):
            parse_header(f)


def test_zero_channels_rejected(tmp_path):
    """A header with n_channels == 0 must be rejected (avoids div-by-zero)."""
    import struct

    from tests.generate_test_file import MAGIC

    header = bytearray(HEADER_SIZE)
    header[0:8] = MAGIC
    header[8:9] = struct.pack("B", 1)
    header[9:10] = struct.pack("B", 0)  # n_channels = 0
    header[10:18] = struct.pack("d", 10_000.0)
    header[18:26] = struct.pack("Q", 0)
    p = tmp_path / "zero_ch.d1f"
    p.write_bytes(bytes(header))
    with open(p, "rb") as f:
        with pytest.raises(ValueError, match="n_channels"):
            parse_header(f)


def test_nonpositive_sample_rate_rejected(tmp_path):
    """A header with sample_rate_hz <= 0 must be rejected."""
    import struct

    from tests.generate_test_file import MAGIC

    header = bytearray(HEADER_SIZE)
    header[0:8] = MAGIC
    header[8:9] = struct.pack("B", 1)
    header[9:10] = struct.pack("B", N_CHANNELS)
    header[10:18] = struct.pack("d", 0.0)  # sample_rate_hz = 0
    header[18:26] = struct.pack("Q", 0)
    p = tmp_path / "zero_rate.d1f"
    p.write_bytes(bytes(header))
    with open(p, "rb") as f:
        with pytest.raises(ValueError, match="sample_rate_hz"):
            parse_header(f)


def test_streaming_stats_truncated_final_row(tiny_d1f, tmp_path):
    """A file whose last row is truncated must not crash streaming_stats."""
    with open(tiny_d1f, "rb") as f:
        h = parse_header(f)
    # Copy the file then chop a few bytes off the end (partial final row).
    data = tiny_d1f.read_bytes()
    truncated = tmp_path / "truncated.d1f"
    truncated.write_bytes(data[:-7])  # 7 bytes < one 24-byte row
    stats = streaming_stats(truncated, h, chunk_rows=1024)
    # Should process all whole rows (9_999 or 10_000 depending on the cut).
    assert stats["n_samples"] >= 9_999
    assert stats["n_channels"] == N_CHANNELS


def test_file_size(tiny_d1f):
    expected = HEADER_SIZE + 10_000 * N_CHANNELS * 4
    assert tiny_d1f.stat().st_size == expected


# ---- streaming stats ----


def test_streaming_stats(tiny_d1f):
    with open(tiny_d1f, "rb") as f:
        h = parse_header(f)
    stats = streaming_stats(tiny_d1f, h, chunk_rows=1024)

    assert stats["n_samples"] == 10_000
    assert stats["n_channels"] == N_CHANNELS
    assert stats["duration_seconds"] == pytest.approx(1.0, rel=1e-3)
    assert len(stats["channels"]) == N_CHANNELS
    for ch in stats["channels"]:
        assert ch["std"] > 0
        assert ch["min"] < ch["mean"] < ch["max"]


def test_streaming_stats_single_chunk(tiny_d1f):
    """Stats must be identical whether computed in one chunk or many."""
    with open(tiny_d1f, "rb") as f:
        h = parse_header(f)
    s1 = streaming_stats(tiny_d1f, h, chunk_rows=10_000)
    s2 = streaming_stats(tiny_d1f, h, chunk_rows=512)
    for i in range(N_CHANNELS):
        assert s1["channels"][i]["mean"] == pytest.approx(
            s2["channels"][i]["mean"], rel=1e-5
        )
        assert s1["channels"][i]["std"] == pytest.approx(
            s2["channels"][i]["std"], rel=1e-5
        )


# ---- strided read ----


def test_strided_read_shape(tiny_d1f):
    with open(tiny_d1f, "rb") as f:
        h = parse_header(f)
    data = strided_read(tiny_d1f, h, target_points=100)
    assert data.ndim == 2
    assert data.shape[1] == N_CHANNELS
    assert data.shape[0] <= 100


def test_strided_read_full_file(tiny_d1f):
    """When target_points >= n_samples, all rows are returned."""
    with open(tiny_d1f, "rb") as f:
        h = parse_header(f)
    data = strided_read(tiny_d1f, h, target_points=100_000)
    assert data.shape[0] == 10_000
    assert data.shape[1] == N_CHANNELS
