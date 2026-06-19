"""Directus REST API write-back client."""

import os

import requests

DIRECTUS_URL: str = os.getenv("DIRECTUS_URL", "http://directus:8055")
_TOKEN: str = os.getenv("WORKER_DIRECTUS_TOKEN", "")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_TOKEN}",
        "Content-Type": "application/json",
    }


def patch_item(collection: str, item_id: str, payload: dict) -> dict:
    """PATCH /items/{collection}/{item_id} — generic write-back."""
    url = f"{DIRECTUS_URL}/items/{collection}/{item_id}"
    resp = requests.patch(url, json=payload, headers=_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_item(collection: str, item_id: str) -> dict:
    """GET /items/{collection}/{item_id} — return the item's data dict.

    Use this for read-merge-write so your plugin doesn't clobber other plugins'
    contributions to shared JSONB columns (e.g. test_sessions.summary_stats).
    """
    url = f"{DIRECTUS_URL}/items/{collection}/{item_id}"
    resp = requests.get(url, headers=_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json().get("data", {})
