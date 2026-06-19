"""Unit tests for FFT analysis and spectrum generation."""

import struct

import numpy as np
import pytest

from app.lib.fft_analysis import analyse_channel, plot_spectrum

D1F_MAGIC = b"D1FORCE\n"
HEADER_SIZE = 64
N_CHANNELS = 6


def make_d1f(path: str, n_samples: int, sample_rate: float, freq_hz: float) -> None:
    """Write a synthetic D1F file with a sine wave on the Fz channel."""
    header = bytearray(HEADER_SIZE)
    header[0:8] = D1F_MAGIC
    header[8:9] = struct.pack("B", 1)
    header[9:10] = struct.pack("B", N_CHANNELS)
    header[10:18] = struct.pack("d", sample_rate)
    header[18:26] = struct.pack("Q", n_samples)

    t = np.arange(n_samples) / sample_rate
    fz = 500.0 * np.sin(2 * np.pi * freq_hz * t).astype(np.float32)
    data = np.column_stack([np.zeros((n_samples,), np.float32)] * N_CHANNELS)
    data[:, 2] = fz  # Fz channel

    with open(path, "wb") as f:
        f.write(bytes(header))
        f.write(data.tobytes())


@pytest.fixture
def sine_signal():
    """1-second sine at 250 Hz, 10 kHz sample rate, 500 N amplitude."""
    sample_rate = 10_000.0
    freq = 250.0
    n = 10_000
    t = np.arange(n) / sample_rate
    return 500.0 * np.sin(2 * np.pi * freq * t), sample_rate, freq


def test_dominant_frequency(sine_signal):
    signal, sample_rate, true_freq = sine_signal
    result = analyse_channel(signal, sample_rate)
    assert result["dominant_frequency_hz"] == pytest.approx(true_freq, rel=0.05)


def test_rms_of_sine(sine_signal):
    signal, sample_rate, _ = sine_signal
    result = analyse_channel(signal, sample_rate)
    expected_rms = 500.0 / np.sqrt(2)
    assert result["rms"] == pytest.approx(expected_rms, rel=0.01)


def test_peak_value(sine_signal):
    signal, sample_rate, _ = sine_signal
    result = analyse_channel(signal, sample_rate)
    assert result["peak"] == pytest.approx(500.0, rel=0.001)


def test_top_frequencies_count(sine_signal):
    signal, sample_rate, _ = sine_signal
    result = analyse_channel(signal, sample_rate, n_top=3)
    assert len(result["top_frequencies"]) == 3


def test_band_energy_keys(sine_signal):
    signal, sample_rate, _ = sine_signal
    result = analyse_channel(signal, sample_rate)
    assert set(result["band_energy"].keys()) == {
        "0_500_hz",
        "500_2000_hz",
        "2000_plus_hz",
    }


def test_plot_spectrum_returns_svg(sine_signal):
    signal, sample_rate, _ = sine_signal
    svg = plot_spectrum(signal, sample_rate, actual_stride=1)
    assert svg.startswith(b"<?xml") or b"<svg" in svg[:200]


def test_d1f_reader(tmp_path):
    """Verify read_channel extracts the correct channel from a D1F file."""
    from app.lib.d1f_reader import parse_header, read_channel

    path = str(tmp_path / "test.d1f")
    make_d1f(path, n_samples=10_000, sample_rate=10_000.0, freq_hz=100.0)

    with open(path, "rb") as f:
        h = parse_header(f)

    assert h["n_samples"] == 10_000
    assert h["n_channels"] == N_CHANNELS

    fz = read_channel(path, h, channel_index=2, max_samples=10_000)
    assert fz.shape[0] == 10_000
    assert np.abs(fz).max() == pytest.approx(500.0, rel=0.01)

    fx = read_channel(path, h, channel_index=0, max_samples=10_000)
    assert np.allclose(fx, 0.0)
