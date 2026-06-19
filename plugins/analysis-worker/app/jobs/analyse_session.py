"""rq job: FFT-based frequency analysis on D1F force files."""

import logging
import os
import tempfile
from pathlib import Path

from app.lib import directus_client, minio_client
from app.lib.d1f_reader import CHANNEL_NAMES, parse_header, read_channel
from app.lib.fft_analysis import analyse_channel, plot_spectrum
from app.lib.statuses import STATUS_ANALYSED, STATUS_ANALYSING, STATUS_FAILED

log = logging.getLogger(__name__)

COLLECTION = "test_sessions"
FFT_CHANNEL_INDEX = int(os.getenv("FFT_CHANNEL_INDEX", "2"))  # default: Fz
FFT_MAX_SAMPLES = int(os.getenv("FFT_MAX_SAMPLES", "131072"))  # 2^17


def analyse_session(session_id: str, object_key: str) -> None:
    """Compute per-channel FFT metrics for a D1F file and write back to Directus.

    Pipeline:
      1. Mark session status = 'analysing'
      2. Download D1F from MinIO to temp file
      3. Parse header
      4. Read primary force channel (Fz by default) with stride
      5. Compute amplitude spectrum + top frequencies + band energy
      6. Generate spectrum SVG plot
      7. Upload SVG to MinIO
      8. PATCH test_sessions with fft_analysis results + plot URI
    """
    log.info("start analysis session=%s object=%s", session_id, object_key)
    _mark(session_id, STATUS_ANALYSING)

    with tempfile.NamedTemporaryFile(suffix=".d1f", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        minio_client.download_file(object_key, tmp_path)

        with open(tmp_path, "rb") as fh:
            header = parse_header(fh)

        n_ch = header["n_channels"]
        ch_idx = min(FFT_CHANNEL_INDEX, n_ch - 1)
        ch_name = (
            CHANNEL_NAMES[ch_idx] if ch_idx < len(CHANNEL_NAMES) else f"Ch{ch_idx}"
        )
        ch_unit = "N" if ch_idx < 3 else "Nm"

        actual_stride = max(1, header["n_samples"] // FFT_MAX_SAMPLES)
        signal = read_channel(tmp_path, header, ch_idx, max_samples=FFT_MAX_SAMPLES)

        metrics = analyse_channel(signal, header["sample_rate_hz"], actual_stride)

        svg_bytes = plot_spectrum(
            signal, header["sample_rate_hz"], actual_stride, ch_name, ch_unit
        )
        plot_key = object_key.rsplit(".", 1)[0] + f"_fft_{ch_name}.svg"
        minio_client.put_object(plot_key, svg_bytes, "image/svg+xml")
        plot_uri = f"minio://{minio_client.BUCKET}/{plot_key}"

        analysis_result = {
            "channel": ch_name,
            "channel_index": ch_idx,
            "n_samples_analysed": len(signal),
            "stride": actual_stride,
            "effective_sample_rate_hz": header["sample_rate_hz"] / actual_stride,
            **metrics,
        }

        # Read-merge-write: namespace under "fft_analysis" and append our plot
        # so we don't clobber the heavy-data worker's "basic" stats.
        merged_stats, merged_plots = _merge_outputs(
            session_id, "fft_analysis", analysis_result, plot_uri
        )
        directus_client.patch_item(
            COLLECTION,
            session_id,
            {
                "status": STATUS_ANALYSED,
                "summary_stats": merged_stats,
                "plot_uris": merged_plots,
            },
        )
        log.info(
            "done analysis session=%s dominant_freq=%.1f Hz",
            session_id,
            metrics.get("dominant_frequency_hz", 0),
        )

    except Exception:
        log.exception("failed analysis session=%s", session_id)
        _mark(session_id, STATUS_FAILED)
        raise

    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            log.warning("could not remove temp file %s", tmp_path)


def _merge_outputs(
    session_id: str, stats_key: str, stats: dict, plot_uri: str
) -> tuple[dict, list]:
    """Merge this worker's outputs into the existing JSONB columns.

    Returns (summary_stats, plot_uris) with our contribution namespaced under
    *stats_key* and our plot appended (deduped). Falls back to a fresh object
    if the current item can't be read.
    """
    try:
        current = directus_client.get_item(COLLECTION, session_id)
    except Exception:
        log.warning("could not read current session=%s; writing fresh", session_id)
        current = {}

    summary_stats = current.get("summary_stats") or {}
    if not isinstance(summary_stats, dict):
        summary_stats = {}
    summary_stats[stats_key] = stats

    plot_uris = current.get("plot_uris") or []
    if not isinstance(plot_uris, list):
        plot_uris = []
    if plot_uri not in plot_uris:
        plot_uris.append(plot_uri)

    return summary_stats, plot_uris


def _mark(session_id: str, status: str) -> None:
    try:
        directus_client.patch_item(COLLECTION, session_id, {"status": status})
    except Exception:
        log.warning("could not set status=%s for session=%s", status, session_id)
