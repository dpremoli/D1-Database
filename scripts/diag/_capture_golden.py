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

OUT = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "tests", "scripts", "diag", "fixtures", "golden_default_recipe.npz",
)


def main() -> None:
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = synthetic_cut()
    cols, metrics = analyse(cache_of(t, fx, fy, fz, rpm, revs, fs), x, y, samples_per_rev=256)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    np.savez_compressed(OUT, **cols, __metrics__=np.array(repr(sorted(metrics.items()))))
    print(f"wrote {OUT}: {len(cols)} columns, n={cols['t'].size}")


if __name__ == "__main__":
    main()
