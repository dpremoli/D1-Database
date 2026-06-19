"""Lightweight request authentication for the plugin API.

Plugins sit on a private Docker network, but defence-in-depth applies: an
attacker reaching the network must not be able to run arbitrary queries through
the text-to-SQL endpoint. Copied verbatim from the plugin template.
"""

import hmac
import logging
import os

from flask import jsonify, request

log = logging.getLogger(__name__)

SECRET_HEADER = "X-Worker-Secret"


def check_secret():
    """Flask before_request hook enforcing the shared-secret header.

    Returns None to allow, or a (response, status) tuple to reject. GET /health
    is exempt. If WORKER_WEBHOOK_SECRET is unset the check is disabled (a warning
    is logged once at import). Set it in production. See .env.example.
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


if not os.getenv("WORKER_WEBHOOK_SECRET"):
    log.warning(
        "WORKER_WEBHOOK_SECRET is not set — webhook authentication is DISABLED."
    )
