# Remote live-backup receiver for force-app recordings. Deployed on d1-server alongside the rest
# of the stack; the acquisition PC streams raw D1RW chunks here during a recording so a local disk
# or machine failure can't take the capture with it.
#
# BACKUP_STORAGE must point at a mounted volume — the default (a dir next to server.py) lives in
# the container's writable layer and would be lost on every recreate, which for a backup service
# is precisely the wrong failure mode.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py ./
COPY test_server.py ./

ENV BACKUP_STORAGE=/data
EXPOSE 8210
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8210/health')"]

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8210"]
