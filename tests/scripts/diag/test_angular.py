import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag.angular import angular_resample, order_spectrum, tsa

SPR = 256


def test_constant_rate_resample_round_trips():
    revs = np.linspace(0.0, 10.0, 10 * SPR + 1)
    sig = np.sin(2 * np.pi * 3.0 * revs)  # order 3
    grid, out = angular_resample(revs, sig, SPR)
    np.testing.assert_allclose(out, np.sin(2 * np.pi * 3.0 * grid), atol=1e-6)


def test_varying_rpm_collapses_swept_tone_to_fixed_order():
    # Spindle accelerates: revs advance quadratically in time. A tone locked to shaft
    # angle is a frequency sweep in time but a single fixed order in the angular domain.
    t = np.linspace(0.0, 10.0, 200_000)
    revs = 0.5 * t**2
    sig = np.sin(2 * np.pi * 5.0 * revs)  # order 5, always
    _, out = angular_resample(revs, sig, SPR)
    orders, amp = order_spectrum(out, SPR)
    assert abs(orders[np.argmax(amp)] - 5.0) < 0.05


def test_tsa_recovers_signature_and_zero_residual_when_perfectly_periodic():
    revs = np.linspace(0.0, 20.0, 20 * SPR + 1)
    sig = np.sin(2 * np.pi * 1.0 * revs) + 0.5 * np.sin(2 * np.pi * 4.0 * revs)
    _, out = angular_resample(revs, sig, SPR)
    signature, residual = tsa(out, SPR)
    assert signature.size == SPR
    assert np.max(np.abs(residual)) < 1e-6


def test_tsa_residual_isolates_a_one_off_event():
    rng = np.random.default_rng(3)
    revs = np.linspace(0.0, 20.0, 20 * SPR + 1)
    sig = np.sin(2 * np.pi * 1.0 * revs)
    _, out = angular_resample(revs, sig, SPR)
    out = out.copy()
    out[5 * SPR + 40] += 10.0  # single implanted spike
    _, residual = tsa(out, SPR)
    assert np.argmax(np.abs(residual)) == 5 * SPR + 40
    assert np.max(np.abs(residual)) > 5.0
    _ = rng


def test_resample_requires_monotonic_revs():
    revs = np.array([0.0, 1.0, 0.5, 2.0])
    with pytest.raises(ValueError, match="monotonic"):
        angular_resample(revs, np.zeros(4), SPR)


def test_order_spectrum_orders_are_in_cycles_per_rev():
    revs = np.linspace(0.0, 32.0, 32 * SPR + 1)
    sig = np.sin(2 * np.pi * 7.0 * revs)
    _, out = angular_resample(revs, sig, SPR)
    orders, amp = order_spectrum(out, SPR)
    assert abs(orders[np.argmax(amp)] - 7.0) < 0.05
