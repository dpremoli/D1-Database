"""REST wiring: start → run to completion → captures endpoints serve the artifacts.
(WebSocket streaming is covered by the frontend end-to-end test.)"""
import time

from fastapi.testclient import TestClient

import app.main as main
from app import d1lc
from app.main import app as fastapi_app


def test_start_run_and_serve(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    with TestClient(fastapi_app) as client:
        r = client.post("/record/start", json={"sample_rate": 2000, "duration_sec": 0.4, "rpm": 1200})
        assert r.status_code == 200, r.text
        cid = r.json()["id"]

        # second start while running is rejected
        assert client.post("/record/start", json={}).status_code == 409

        # wait for natural completion
        for _ in range(100):
            st = client.get("/record/status").json()
            if st["state"] in ("done", "error"):
                break
            time.sleep(0.1)
        assert st["state"] == "done", st

        assert cid in client.get("/captures").json()["captures"]
        summ = client.get(f"/captures/{cid}/summary").json()
        assert summ["n"] > 0 and set(("Fx", "Fy", "Fz")) <= set(summ["peaks"])
        cache = client.get(f"/captures/{cid}/live_cache.bin")
        assert cache.status_code == 200
        assert d1lc.read_d1lc_header(cache.content)["n"] > 0  # valid D1LC
