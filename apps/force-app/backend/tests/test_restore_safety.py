"""POST /backup/restore must never destroy local data (#82), and recover/discard must not race.

The "remote" is a real HTTP server on localhost that serves a raw file and a recording config, and
can cut a download off part-way, so the download code really writes (and really fails).
"""

from __future__ import annotations

import http.server
import json
import os
import threading

import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import backup as backup_mod
from app import recovery
from app.config import RecordConfig
from app.d1rw import RawWriter
from app.main import app as fastapi_app
from app.recovery import write_manifest

SID = "20261001-100000-abc"


def _write_raw(path: str, rows: int) -> bytes:
    w = RawWriter(path, n_cols=10, rate=2000.0, start_unix=1_700_000_000.0)
    if rows:
        w.append(np.arange(rows) / 2000.0, np.ones((rows, 9)))
    w.close()
    with open(path, "rb") as f:
        return f.read()


class _Remote:
    def __init__(self, raw: bytes, config: dict | None, cut_after: int | None = None, on_raw=None):
        outer = self
        self.raw, self.config, self.cut_after = raw, config, cut_after
        self.on_raw = on_raw  # called (in the server thread) when the raw download is requested

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):  # noqa: N802 (http.server dispatches on this name)
                if self.path.endswith("/raw"):
                    if outer.on_raw:
                        outer.on_raw()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(outer.raw)))
                    self.end_headers()
                    body = outer.raw if outer.cut_after is None else outer.raw[: outer.cut_after]
                    self.wfile.write(body)
                    self.wfile.flush()
                    self.close_connection = True  # short body + Content-Length = IncompleteRead
                elif self.path.endswith("/info"):
                    data = json.dumps({"meta": {"config": outer.config}}).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_response(404)
                    self.end_headers()

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    monkeypatch.setattr(main, "_session", None)
    remotes: list[_Remote] = []

    def make(raw: bytes, config="default", cut_after=None, on_raw=None) -> _Remote:
        cfg = (
            RecordConfig(sample_rate=2000, sample_name="REMOTE-1").model_dump()
            if config == "default"
            else config
        )
        r = _Remote(raw, cfg, cut_after, on_raw)
        remotes.append(r)
        backup_mod.save_config(str(tmp_path), {"enabled": True, "server_url": r.url})
        return r

    with TestClient(fastapi_app) as c:
        yield c, tmp_path, make
    for r in remotes:
        r.close()


def _local_incomplete(root, rows: int) -> tuple[str, bytes]:
    d = os.path.join(str(root), SID)
    os.makedirs(d)
    raw = _write_raw(os.path.join(d, "raw.d1raw"), rows)
    write_manifest(d, "recording", RecordConfig(sample_rate=2000, sample_name="LOCAL-1"))
    return d, raw


def _snapshot(d: str) -> dict[str, bytes]:
    out = {}
    for n in sorted(os.listdir(d)):
        with open(os.path.join(d, n), "rb") as f:
            out[n] = f.read()
    return out


def test_failed_download_keeps_the_local_raw_byte_identical(env):
    client, root, make = env
    d, local = _local_incomplete(root, rows=4000)
    before = _snapshot(d)
    remote_raw = _write_raw(str(root / "remote.d1raw"), 3000)
    make(remote_raw, cut_after=len(remote_raw) // 2)
    r = client.post(f"/backup/restore/{SID}")
    assert r.status_code == 502
    assert "local copy was not changed" in r.json()["detail"]
    assert _snapshot(d) == before  # raw AND manifest untouched, no .part left behind


def test_failed_download_into_a_new_dir_leaves_nothing(env):
    client, root, make = env
    remote_raw = _write_raw(str(root / "remote.d1raw"), 3000)
    make(remote_raw, cut_after=100)
    assert client.post(f"/backup/restore/{SID}").status_code == 502
    assert not os.path.exists(os.path.join(str(root), SID))


def test_existing_incomplete_capture_that_is_longer_is_refused(env):
    client, root, make = env
    d, _ = _local_incomplete(root, rows=4000)
    before = _snapshot(d)
    make(_write_raw(str(root / "remote.d1raw"), 3000))  # remote is the SHORTER copy
    r = client.post(f"/backup/restore/{SID}")
    assert r.status_code == 409
    assert _snapshot(d) == before


def test_longer_remote_replaces_but_keeps_the_local_raw_aside(env):
    client, root, make = env
    d, local = _local_incomplete(root, rows=2000)
    remote_raw = _write_raw(str(root / "remote.d1raw"), 5000)
    make(remote_raw)
    r = client.post(f"/backup/restore/{SID}")
    assert r.status_code == 200, r.text
    aside = r.json()["local_copy_kept_as"]
    with open(os.path.join(d, aside), "rb") as f:
        assert f.read() == local  # the local rows are still there, untouched
    with open(os.path.join(d, "raw.d1raw"), "rb") as f:
        assert f.read() == remote_raw
    # the local recording's own manifest (LOCAL-1) is kept rather than replaced by the remote's
    assert json.load(open(os.path.join(d, "summary.json")))["sample_name"] == "LOCAL-1"


def test_failed_finalize_puts_the_local_raw_back(env, monkeypatch):
    client, root, make = env
    d, local = _local_incomplete(root, rows=2000)
    make(_write_raw(str(root / "remote.d1raw"), 5000))

    def boom(*a, **k):
        raise RuntimeError("finalize broke")

    monkeypatch.setattr(recovery, "recover_session", boom)
    r = client.post(f"/backup/restore/{SID}")
    assert r.status_code == 500
    assert _snapshot(d)["raw.d1raw"] == local
    assert not [n for n in os.listdir(d) if ".local-" in n or n.endswith(".part")]


def test_clean_restore_into_a_new_dir_still_works(env):
    client, root, make = env
    remote_raw = _write_raw(str(root / "remote.d1raw"), 3000)
    make(remote_raw)
    r = client.post(f"/backup/restore/{SID}")
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["n"] == 3000
    assert not os.path.exists(os.path.join(str(root), SID, "raw.d1raw.part"))


def test_restore_of_the_active_session_is_refused(env, monkeypatch):
    client, root, make = env
    make(_write_raw(str(root / "remote.d1raw"), 100))
    monkeypatch.setattr(main, "_active_session_id", lambda: SID)
    assert client.post(f"/backup/restore/{SID}").status_code == 409
    assert not os.path.exists(os.path.join(str(root), SID))


# ---- #83: recover vs discard ------------------------------------------------------------------


def test_discard_is_refused_while_the_same_id_is_being_recovered(env):
    client, root, _ = env
    _local_incomplete(root, rows=100)
    recovery._recovering.add(SID)
    try:
        assert client.post(f"/recovery/discard/{SID}").status_code == 409
        assert client.post(f"/recovery/recover/{SID}").status_code == 409  # second recover too
        assert os.path.isdir(os.path.join(str(root), SID))
    finally:
        recovery._recovering.discard(SID)


def test_recover_clears_its_marker_afterwards_even_on_failure(env, monkeypatch):
    client, root, _ = env
    _local_incomplete(root, rows=100)
    monkeypatch.setattr(
        recovery, "recover_session", lambda *a: (_ for _ in ()).throw(RuntimeError("x"))
    )
    assert client.post(f"/recovery/recover/{SID}").status_code == 500
    assert SID not in recovery._recovering


def test_recover_refuses_a_discard_in_flight(env):
    client, root, _ = env
    _local_incomplete(root, rows=100)
    recovery._discarding.add(SID)
    try:
        assert client.post(f"/recovery/recover/{SID}").status_code == 409
    finally:
        recovery._discarding.discard(SID)


# ---- #7 + id hardening -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "a\\b"])
def test_is_safe_id_rejects_names_that_point_at_the_root(bad):
    assert recovery.is_safe_id(bad) is False


def test_non_numeric_updated_at_does_not_break_the_list(env, monkeypatch):
    client, root, _ = env
    backup_mod.save_config(str(root), {"enabled": True, "server_url": "http://b:1"})
    monkeypatch.setattr(
        backup_mod,
        "fetch_remote_sessions",
        lambda url, timeout=8.0: {
            "retention_hours": 12,
            "sessions": [
                {"id": "good", "state": "complete", "meta": {"updated_at": 1_700_000_000}},
                {"id": "bad", "state": "complete", "meta": {"updated_at": "yesterday"}},
            ],
        },
    )
    r = client.get("/backup/remote-sessions")
    assert r.status_code == 200
    by_id = {s["id"]: s for s in r.json()["sessions"]}
    assert by_id["good"]["expires_at"] == 1_700_000_000 + 12 * 3600
    assert by_id["bad"]["expires_at"] is None


def test_a_200_without_sessions_is_an_error_not_an_empty_list(monkeypatch):
    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"status": "ok"}'

    monkeypatch.setattr(backup_mod.urllib.request, "urlopen", lambda *a, **k: R())
    with pytest.raises(backup_mod.RemoteBackupError):
        backup_mod.fetch_remote_sessions("http://x")
