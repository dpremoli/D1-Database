import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag.envelope import bandpass_envelope, envelope_spectrum


def _am_signal(fs, duration, carrier, mod_rate, mod_depth=0.8, noise=0.05, seed=0):
    """A carrier amplitude-modulated at mod_rate -- the synthetic stand-in for a structural
    resonance being excited at some repetition rate the dynamometer can't directly resolve."""
    t = np.arange(0, duration, 1.0 / fs)
    rng = np.random.default_rng(seed)
    sig = (1.0 + mod_depth * np.sin(2 * np.pi * mod_rate * t)) * np.sin(
        2 * np.pi * carrier * t
    )
    sig = sig + noise * rng.normal(size=t.size)
    return sig


def test_bandpass_envelope_recovers_the_modulation_rate():
    # THE ground-truth test: a carrier the dyno resonance stands in for, modulated at a rate
    # that itself is far above what could be measured directly, must come back from the
    # envelope's own spectrum -- this is the whole point of the technique.
    fs = 25_000.0
    sig = _am_signal(fs, duration=2.0, carrier=2000.0, mod_rate=50.0)
    envelope = bandpass_envelope(sig, fs, f_center=2000.0, bandwidth_frac=0.2)
    freqs, amp = envelope_spectrum(envelope, fs, max_freq=500.0)
    peak_freq = freqs[np.argmax(amp)]
    assert abs(peak_freq - 50.0) < 10.0


def test_bandpass_envelope_output_is_non_negative_and_same_length():
    fs = 25_000.0
    sig = _am_signal(fs, duration=1.0, carrier=2000.0, mod_rate=50.0)
    envelope = bandpass_envelope(sig, fs, f_center=2000.0)
    assert envelope.shape == sig.shape
    assert np.all(envelope >= 0.0)


def test_bandpass_envelope_rejects_a_band_that_does_not_fit_below_nyquist():
    fs = 1000.0  # Nyquist = 500 Hz
    sig = np.zeros(2000)
    with pytest.raises(ValueError, match="Nyquist"):
        bandpass_envelope(sig, fs, f_center=2000.0, bandwidth_frac=0.2)


def test_bandpass_envelope_rejects_a_center_frequency_at_or_below_zero():
    fs = 25_000.0
    sig = np.zeros(2000)
    with pytest.raises(ValueError, match="f_center"):
        bandpass_envelope(sig, fs, f_center=0.0)


def test_envelope_spectrum_max_freq_caps_the_returned_range():
    fs = 25_000.0
    sig = _am_signal(fs, duration=1.0, carrier=2000.0, mod_rate=50.0)
    envelope = bandpass_envelope(sig, fs, f_center=2000.0)
    freqs, amp = envelope_spectrum(envelope, fs, max_freq=100.0)
    assert freqs.max() <= 100.0
    assert amp.shape == freqs.shape
