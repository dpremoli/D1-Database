"""rq job: download a D1F file from MinIO, compute stats, render plot, write back."""

import logging
import os
import tempfile
from pathlib import Path

from app.lib import directus_client, minio_client
from app.lib.parser import parse_header, strided_read
from app.lib.plotter import plot_overview
from app.lib.stats import streaming_stats

log = logging.getLogger(__name__)

MEMORY_LIMIT_MB: int = int(os.getenv("WORKER_MEMORY_LIMIT_MB", "256"))
PLOT_MAX_POINTS: int = int(os.getenv("PLOT_MAX_POINTS", "10000"))


def process_session(session_id: str, object_key: str) -> None:
    """End-to-end processing job enqueued via the webhook endpoint.

    Steps:
      1. Mark session status = processing
      2. Stream-download the D1F file from MinIO to a temp file
      3. Parse the 64-byte header
      4. Compute per-channel stats in bounded-size chunks
      5. Generate a downsampled overview SVG plot
      6. Upload the SVG to MinIO
      7. PATCH test_sessions with stats + plot URI + status = processed
    """
    log.info("start session=%s object=%s", session_id, object_key)
    _mark(session_id, "processing")

    with tempfile.NamedTemporaryFile(suffix=".d1f", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        minio_client.download_file(object_key, tmp_path)

        with open(tmp_path, "rb") as fh:
            header = parse_header(fh)

        # chunk_rows chosen so chunk ≤ MEMORY_LIMIT_MB of float32 data
        chunk_rows = max(
            1024, (MEMORY_LIMIT_MB * 1024 * 1024) // (header["n_channels"] * 4)
        )
        stats = streaming_stats(tmp_path, header, chunk_rows=chunk_rows)

        plot_data = strided_read(tmp_path, header, target_points=PLOT_MAX_POINTS)
        svg_bytes = plot_overview(plot_data, header, title=object_key)

        plot_key = object_key.rsplit(".", 1)[0] + "_overview.svg"
        minio_client.put_object(plot_key, svg_bytes, "image/svg+xml")
        plot_uri = f"minio://{minio_client.BUCKET}/{plot_key}"

        directus_client.patch_test_session(
            session_id,
            {
                "status": "processed",
                "summary_stats": stats,
                "plot_uris": [plot_uri],
            },
        )
        log.info("done session=%s", session_id)

    except Exception:
        log.exception("failed session=%s", session_id)
        _mark(session_id, "error")
        raise

    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _mark(session_id: str, status: str) -> None:
    try:
        directus_client.patch_test_session(session_id, {"status": status})
    except Exception:
        log.warning("could not set status=%s for session=%s", status, session_id)
