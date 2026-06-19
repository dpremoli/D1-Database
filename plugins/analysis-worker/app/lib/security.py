"""Lightweight request authentication for the analysis-worker webhook.

The worker is on a private Docker network, but defence-in-depth applies: an
attacker reaching the network must not be able to enqueue arbitrary jobs.
"""

import hmac
import logging
import os
import re

from flask import jsonify, request

log = logging.getLogger(__name__)

SECRET_HEADER = "X-Worker-Secret"
_OBJECT_KEY_RE = re.compile(r"^[A-Za-z0-9._/\-]+$")


def check_secret():
    """Flask before_request hook enforcing the shared-secret header.

    Returns None to allow, or a (response, status) tuple to reject. GET /health
    is exempt. If WORKER_WEBHOOK_SECRET is unset the check is disabled (a warning
    is logged once at import). See .env.example.
    """
    if request.method == "GET" and request.path == "/health":
        return None
    expected = os.getenv("WORKER_WEBHOOK_SECRET", "")
    if not expected:
        return None
    provided = request.headers.get(SECRET_HEADER, "")
    if not hmac.compare_digest(provided, expected):
        return jsonify({"error": "unauthorized"}), 401
    return None


def valid_object_key(key: str) -> bool:
    """True if *key* is a safe S3 object key (no traversal, allowed chars only)."""
    return bool(key) and ".." not in key and bool(_OBJECT_KEY_RE.match(key))


if not os.getenv("WORKER_WEBHOOK_SECRET"):
    log.warning(
        "WORKER_WEBHOOK_SECRET is not set — webhook authentication is DISABLED."
    )
