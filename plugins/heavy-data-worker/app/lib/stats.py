"""Streaming per-channel statistics computed with bounded memory."""

from pathlib import Path

import numpy as np

from app.lib.parser import HEADER_SIZE, FileHeader


def streaming_stats(
    filepath: str | Path,
    header: FileHeader,
    chunk_rows: int = 65_536,
) -> dict:
    """Compute per-channel min / max / mean / std over the entire file.

    Reads at most *chunk_rows* rows at a time.  Peak memory:
      chunk_rows × n_channels × 4 bytes (float32 → float64 promotion included).
    """
    n_ch = header["n_channels"]
    row_bytes = n_ch * 4

    running_min = np.full(n_ch, np.inf, dtype=np.float64)
    running_max = np.full(n_ch, -np.inf, dtype=np.float64)
    running_sum = np.zeros(n_ch, dtype=np.float64)
    running_sum_sq = np.zeros(n_ch, dtype=np.float64)
    total_rows = 0

    with open(filepath, "rb") as f:
        f.seek(HEADER_SIZE)
        while True:
            raw = f.read(chunk_rows * row_bytes)
            if not raw:
                break
            chunk = (
                np.frombuffer(raw, dtype=np.float32)
                .reshape(-1, n_ch)
                .astype(np.float64)
            )
            running_min = np.minimum(running_min, chunk.min(axis=0))
            running_max = np.maximum(running_max, chunk.max(axis=0))
            running_sum += chunk.sum(axis=0)
            running_sum_sq += (chunk**2).sum(axis=0)
            total_rows += len(chunk)

    if total_rows == 0:
        return {"error": "empty file", "n_samples": 0}

    mean = running_sum / total_rows
    variance = np.maximum(running_sum_sq / total_rows - mean**2, 0.0)
    std = np.sqrt(variance)

    return {
        "n_samples": total_rows,
        "n_channels": n_ch,
        "sample_rate_hz": header["sample_rate_hz"],
        "duration_seconds": total_rows / header["sample_rate_hz"],
        "channels": [
            {
                "index": i,
                "min": float(running_min[i]),
                "max": float(running_max[i]),
                "mean": float(mean[i]),
                "std": float(std[i]),
            }
            for i in range(n_ch)
        ],
    }
