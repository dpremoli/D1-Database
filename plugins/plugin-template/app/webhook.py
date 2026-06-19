"""Webhook receiver for the plugin.

Endpoints:
  GET  /health                — liveness probe
  POST /api/webhook/session   — Directus Flow callback; enqueues processing job

Replace example_job with your job in the import below and in _queue.enqueue().
"""

import os

from flask import Flask, jsonify, request
from redis import Redis
from rq import Queue

from app.jobs.example_job import example_job
from app.lib import minio_client

app = Flask(__name__)

_redis = Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=int(os.getenv("REDIS_PORT", "6379")),
)
_queue = Queue(os.getenv("QUEUE_NAME", "plugin"), connection=_redis)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/api/webhook/session")
def webhook_session():
    """Directus Flow callback — enqueue a job for a new/updated test_session."""
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

    job = _queue.enqueue(example_job, session_id, object_key)
    return jsonify({"job_id": job.id}), 202
