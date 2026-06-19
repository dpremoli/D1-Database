"""Webhook receiver for the analysis worker.

Endpoints:
  GET  /health                — liveness probe
  POST /api/webhook/session   — Directus Flow callback; enqueues FFT analysis job
"""

import os

from flask import Flask, jsonify, request
from redis import Redis
from rq import Queue

from app.jobs.analyse_session import analyse_session
from app.lib import minio_client
from app.lib.security import check_secret, valid_object_key

app = Flask(__name__)
app.before_request(check_secret)

_redis = Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=int(os.getenv("REDIS_PORT", "6379")),
)
_queue = Queue("analysis", connection=_redis)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/api/webhook/session")
def webhook_session():
    """Directus Flow callback — enqueue FFT analysis for a test_session."""
    payload = request.get_json(force=True)

    session_id = payload.get("key") or payload.get("session_id")
    item_payload = payload.get("payload") or payload
    raw_pointer: str = item_payload.get("file_storage_pointer", "")
    prefix = f"minio://{minio_client.BUCKET}/"
    if raw_pointer.startswith(prefix):
        object_key = raw_pointer[len(prefix) :]
    else:
        object_key = raw_pointer

    if not session_id or not object_key:
        return jsonify({"error": "missing session_id or file_storage_pointer"}), 400
    if not valid_object_key(object_key):
        return jsonify({"error": "invalid object_key"}), 400

    job = _queue.enqueue(analyse_session, session_id, object_key)
    return jsonify({"job_id": job.id}), 202
