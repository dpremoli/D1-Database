# Build context is the REPO ROOT (see docker-compose.yml) so scripts/diag can be copied in
# verbatim — the service runs the identical recipe engine the orchestrator's bake uses, never
# a reimplementation.
FROM python:3.12-slim

WORKDIR /app

COPY plugins/diag-service/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/diag/ ./diag/
COPY plugins/diag-service/app/ ./app/
COPY plugins/diag-service/tests/ ./tests/

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=25s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
