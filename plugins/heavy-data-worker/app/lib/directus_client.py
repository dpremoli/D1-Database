"""Directus REST API write-back client for the heavy-data worker."""

import os

import requests

DIRECTUS_URL: str = os.getenv("DIRECTUS_URL", "http://directus:8055")
_TOKEN: str = os.getenv("WORKER_DIRECTUS_TOKEN", "")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_TOKEN}",
        "Content-Type": "application/json",
    }


def patch_test_session(session_id: str, payload: dict) -> dict:
    """PATCH /items/test_sessions/{session_id} — update status / stats / plots."""
    url = f"{DIRECTUS_URL}/items/test_sessions/{session_id}"
    resp = requests.patch(url, json=payload, headers=_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_test_session(session_id: str) -> dict:
    """GET /items/test_sessions/{session_id} — return the item's data dict.

    Used to read-merge-write summary_stats / plot_uris so that the analysis
    worker and this worker don't clobber each other's contributions to the
    same JSONB columns.
    """
    url = f"{DIRECTUS_URL}/items/test_sessions/{session_id}"
    resp = requests.get(url, headers=_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json().get("data", {})
