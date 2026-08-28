# Bug-report relay for force-app clients. Deployed on d1-server so the GitHub App private key
# lives in exactly one place instead of on every acquisition PC that ships the force-app backend.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py ./
COPY test_server.py ./

EXPOSE 8211
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8211/health')"]

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8211"]
