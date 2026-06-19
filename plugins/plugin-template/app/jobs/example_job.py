"""Stub rq job — replace with your plugin's processing logic."""

import logging
import tempfile
from pathlib import Path

from app.lib import directus_client, minio_client

log = logging.getLogger(__name__)

COLLECTION = "test_sessions"


def example_job(session_id: str, object_key: str) -> None:
    """Download *object_key* from MinIO, process it, write results back.

    Steps to customise:
      1. Replace the placeholder processing below with your analysis logic.
      2. Rename this file and the import in app/webhook.py.
      3. Update the result dict sent to patch_item with your output fields.
    """
    log.info("start session=%s object=%s", session_id, object_key)
    _mark(session_id, "processing")

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        minio_client.download_file(object_key, tmp_path)

        # --- Replace everything below with your analysis logic. ---
        file_size = Path(tmp_path).stat().st_size
        result = {"bytes_processed": file_size}
        # --- End of placeholder. ---

        directus_client.patch_item(
            COLLECTION,
            session_id,
            {"status": "processed", "summary_stats": result},
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
        directus_client.patch_item(COLLECTION, session_id, {"status": status})
    except Exception:
        log.warning("could not set status=%s for session=%s", status, session_id)
