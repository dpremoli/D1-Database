#!/bin/bash
set -e

_term() {
    kill "$WEBHOOK_PID" "$WORKER_PID" 2>/dev/null || true
}
trap _term TERM INT

gunicorn \
    --bind "0.0.0.0:${WORKER_HTTP_PORT:-8080}" \
    --workers 2 \
    --timeout 30 \
    "app.webhook:app" &
WEBHOOK_PID=$!

rq worker \
    --url "redis://${REDIS_HOST:-redis}:${REDIS_PORT:-6379}" \
    heavy-data &
WORKER_PID=$!

wait "$WEBHOOK_PID" "$WORKER_PID"
