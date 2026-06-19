#!/bin/bash
# Text-to-SQL is a synchronous request/response API (no rq worker): a question
# in, guarded SQL and rows out. Only gunicorn runs here.
set -e

exec gunicorn \
    --bind "0.0.0.0:${WORKER_HTTP_PORT:-8080}" \
    --workers 2 \
    --timeout "${LLM_HTTP_TIMEOUT_S:-180}" \
    "app.api:app"
