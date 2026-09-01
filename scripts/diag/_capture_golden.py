"""One-shot: freeze today's analyse() output as the refactor's golden reference.

Deleted once the registry refactor is proven equivalent (see the plan's Task 7). Run from
the repo root:  py scripts/diag/_capture_golden.py
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "tests", "scripts", "diag")
)

from conftest import cache_of, synthetic_cut  # noqa: E402

from diag.pipeline import analyse  # noqa: E402

_FIX = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "scripts", "diag", "fixtures")
OUT = os.path.join(_FIX, "golden_default_recipe.npz")
OUT_ENV = os.path.join(_FIX, "golden_envelope.npz")


def _write(path: str, cols: dict, metrics: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    np.savez_compressed(path, **cols, __metrics__=np.array(repr(sorted(metrics.items()))))
    print(f"wrote {path}: {len(cols)} columns, n={cols['t'].size}")


def main() -> None:
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = synthetic_cut()
    cache = cache_of(t, fx, fy, fz, rpm, revs, fs)
    cols, metrics = analyse(cache, x, y, samples_per_rev=256)
    _write(OUT, cols, metrics)

    # Second fixture: fn_hz=1000.0 keeps the envelope band-pass + Hilbert path inside Nyquist
    # (~2560 Hz) so env_band is genuinely computed, not the all-zeros refusal stub.
    env_cols, env_metrics = analyse(cache, x, y, samples_per_rev=256, fn_hz=1000.0)
    _write(OUT_ENV, env_cols, env_metrics)
    print(f"  env_band_status={env_metrics['env_band_status']!r}")


if __name__ == "__main__":
    main()
