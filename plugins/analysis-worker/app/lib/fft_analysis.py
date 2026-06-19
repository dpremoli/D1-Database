"""FFT-based frequency analysis for D1F force data."""

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np


def analyse_channel(
    signal: np.ndarray,
    sample_rate_hz: float,
    actual_stride: int = 1,
    n_top: int = 5,
) -> dict:
    """Compute FFT spectrum of *signal* and return key frequency metrics.

    Args:
        signal: 1-D array, already strided (every *actual_stride*-th sample)
        sample_rate_hz: original acquisition sample rate in Hz
        actual_stride: stride factor used when reading — determines effective rate
        n_top: number of top-magnitude frequencies to return
    """
    effective_rate = sample_rate_hz / actual_stride
    n = len(signal)
    if n < 2:
        return {"error": "insufficient samples"}

    signal_zero_mean = signal - signal.mean()
    spectrum = np.abs(np.fft.rfft(signal_zero_mean)) * (2.0 / n)
    freqs = np.fft.rfftfreq(n, d=1.0 / effective_rate)

    rms = float(np.sqrt(np.mean(signal**2)))
    peak = float(np.abs(signal).max())
    dominant_idx = int(np.argmax(spectrum[1:]) + 1)  # skip DC

    top_indices = np.argsort(spectrum[1:])[-n_top:][::-1] + 1
    top_freqs = [
        {"frequency_hz": float(freqs[i]), "magnitude": float(spectrum[i])}
        for i in top_indices
    ]

    band_energy = {
        "0_500_hz": float(np.sum(spectrum[(freqs >= 0) & (freqs < 500)] ** 2)),
        "500_2000_hz": float(np.sum(spectrum[(freqs >= 500) & (freqs < 2000)] ** 2)),
        "2000_plus_hz": float(np.sum(spectrum[freqs >= 2000] ** 2)),
    }

    return {
        "rms": rms,
        "peak": peak,
        "dominant_frequency_hz": float(freqs[dominant_idx]),
        "dominant_magnitude": float(spectrum[dominant_idx]),
        "top_frequencies": top_freqs,
        "band_energy": band_energy,
    }


def plot_spectrum(
    signal: np.ndarray,
    sample_rate_hz: float,
    actual_stride: int,
    channel_name: str = "Fz",
    channel_unit: str = "N",
) -> bytes:
    """Return SVG bytes of the one-sided amplitude spectrum."""
    effective_rate = sample_rate_hz / actual_stride
    n = len(signal)
    signal_zero_mean = signal - signal.mean()
    spectrum = np.abs(np.fft.rfft(signal_zero_mean)) * (2.0 / n)
    freqs = np.fft.rfftfreq(n, d=1.0 / effective_rate)

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(freqs[1:], spectrum[1:], linewidth=0.6)
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel(f"Amplitude ({channel_unit})")
    ax.set_title(f"Amplitude Spectrum — {channel_name}")
    ax.grid(alpha=0.3)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()
