#!/usr/bin/env python3
"""Generate a synthetic D1 Force (.d1f) file for testing.

Usage:
    python tests/generate_test_file.py --output /tmp/test.d1f --n-samples 10000
    python tests/generate_test_file.py --output /tmp/large.d1f --n-samples 25000000
      # 25M × 6 ch × 4 bytes ≈ 572 MB
"""
import argparse
import struct

import numpy as np

MAGIC = b"D1FORCE\n"
HEADER_SIZE = 64
N_CHANNELS = 6

# Realistic channel amplitudes: [Fx, Fy, Fz, Mx, My, Mz]
CHANNEL_AMPLITUDES = [500.0, 200.0, 1500.0, 10.0, 5.0, 20.0]


def write_d1f(
    path: str,
    n_samples: int,
    sample_rate_hz: float = 10_000.0,
    n_channels: int = N_CHANNELS,
) -> None:
    """Write a synthetic D1F file with sinusoidal data plus Gaussian noise."""
    header = bytearray(HEADER_SIZE)
    header[0:8] = MAGIC
    header[8:9] = struct.pack("B", 1)
    header[9:10] = struct.pack("B", n_channels)
    header[10:18] = struct.pack("d", sample_rate_hz)
    header[18:26] = struct.pack("Q", n_samples)

    rng = np.random.default_rng(42)
    t = np.arange(n_samples, dtype=np.float64) / sample_rate_hz

    with open(path, "wb") as f:
        f.write(bytes(header))
        chunk = 65_536
        amps = CHANNEL_AMPLITUDES[:n_channels]
        for start in range(0, n_samples, chunk):
            end = min(start + chunk, n_samples)
            tc = t[start:end]
            cols = [
                amp * (np.sin(2 * np.pi * 50 * tc) + 0.1 * rng.standard_normal(len(tc)))
                for amp in amps
            ]
            data = np.column_stack(cols).astype(np.float32)
            f.write(data.tobytes())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a synthetic D1F file")
    parser.add_argument("--output", default="/tmp/test.d1f")
    parser.add_argument("--n-samples", type=int, default=10_000)
    parser.add_argument("--sample-rate", type=float, default=10_000.0)
    args = parser.parse_args()

    write_d1f(args.output, args.n_samples, args.sample_rate)
    size_mb = (HEADER_SIZE + args.n_samples * N_CHANNELS * 4) / 1024 / 1024
    print(f"Written {args.output} ({size_mb:.2f} MB, {args.n_samples:,} samples)")
