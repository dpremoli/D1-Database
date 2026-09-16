"""Tests for the /logs endpoints backing Settings > Logs."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import _parse_log_lines, _read_log_tail, app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_file_log_formatter_uses_utc_not_local_time():
    # #45: the in-app log viewer's ts column is labeled/assumed UTC, but a plain logging.Formatter
    # defaults to localtime -- verify the file handler's formatter was actually switched to
    # time.gmtime, not just that timestamps get produced at all.
    import time

    assert main._file_formatter.converter is time.gmtime


def test_parses_the_formatter_output():
    recs = _parse_log_lines(
        [
            "2026-08-22 22:41:59,123 INFO force_app.main: record_stop: id=abc state=recording",
            "2026-08-22 22:42:00,001 WARNING force_app.nidaq: stop() waited 0.20s",
        ]
    )
    assert [r["level"] for r in recs] == ["INFO", "WARNING"]
    assert recs[0]["logger"] == "force_app.main"
    assert recs[0]["message"] == "record_stop: id=abc state=recording"
    assert recs[1]["ts"] == "2026-08-22 22:42:00,001"


def test_traceback_lines_attach_to_their_record():
    """Unmatched lines must not be dropped — a traceback is exactly what a log view is opened for."""
    recs = _parse_log_lines(
        [
            "2026-08-22 22:41:59,123 ERROR force_app.session: finalize blew up",
            "Traceback (most recent call last):",
            '  File "app/finalize.py", line 1, in finalize',
            "ValueError: boom",
        ]
    )
    assert len(recs) == 1
    assert recs[0]["message"].startswith("finalize blew up\nTraceback")
    assert recs[0]["message"].endswith("ValueError: boom")


def test_leading_unmatched_lines_are_kept():
    recs = _parse_log_lines(["uvicorn startup noise before any formatted record"])
    assert len(recs) == 1 and recs[0]["logger"] == ""


def test_reads_rotated_files_oldest_first(tmp_path, monkeypatch):
    """History spans backend.log plus .1/.2/.3, with the HIGHEST suffix the OLDEST."""
    log_path = tmp_path / "backend.log"
    log_path.write_text("newest\n", encoding="utf-8")
    (tmp_path / "backend.log.1").write_text("middle\n", encoding="utf-8")
    (tmp_path / "backend.log.2").write_text("oldest\n", encoding="utf-8")
    monkeypatch.setattr(main, "LOG_PATH", str(log_path))

    assert _read_log_tail(100) == ["oldest", "middle", "newest"]


def test_tail_limit_returns_the_most_recent(tmp_path, monkeypatch):
    log_path = tmp_path / "backend.log"
    log_path.write_text("\n".join(f"line{i}" for i in range(50)) + "\n", encoding="utf-8")
    monkeypatch.setattr(main, "LOG_PATH", str(log_path))

    tail = _read_log_tail(5)
    assert tail == [f"line{i}" for i in range(45, 50)]


def test_no_log_file_reports_unavailable_rather_than_failing(monkeypatch, client):
    """Logging degrades to stderr-only on an unwritable dir; the endpoint must say so, not 500."""
    monkeypatch.setattr(main, "LOG_PATH", "")
    body = client.get("/logs").json()
    assert body["available"] is False and body["records"] == []
    assert client.get("/logs/download").status_code == 404


# The filtering tests below drive a log file they control rather than emitting through `logging`.
# Under pytest the app's own file handler is never attached — pytest's logging plugin configures
# the root logger first, which makes main.py's logging.basicConfig() a no-op — so emitted records
# never reach the file. Asserting against live emission would be testing the ambient logging
# config, and would pass on pre-existing history rather than on anything the test wrote.
SAMPLE_LOG = (
    "\n".join(
        [
            "2026-08-22 22:00:00,000 DEBUG force_app.main: a debug line",
            "2026-08-22 22:00:01,000 INFO force_app.main: an info line",
            "2026-08-22 22:00:02,000 WARNING force_app.nidaq: stop() waited 0.20s",
            "2026-08-22 22:00:03,000 ERROR force_app.session: finalize error: boom",
            "2026-08-22 22:00:04,000 INFO force_app.backup: distinctive-needle-xyz in the message",
        ]
    )
    + "\n"
)


@pytest.fixture
def sample_log(tmp_path, monkeypatch):
    p = tmp_path / "backend.log"
    p.write_text(SAMPLE_LOG, encoding="utf-8")
    monkeypatch.setattr(main, "LOG_PATH", str(p))
    return p


def test_level_filter_is_severity_and_above(client, sample_log):
    all_recs = client.get("/logs").json()["records"]
    assert [r["level"] for r in all_recs] == ["DEBUG", "INFO", "WARNING", "ERROR", "INFO"]

    warn = client.get("/logs", params={"level": "WARNING"}).json()["records"]
    assert [r["level"] for r in warn] == ["WARNING", "ERROR"]

    info = client.get("/logs", params={"level": "INFO"}).json()["records"]
    assert "DEBUG" not in [r["level"] for r in info]


def test_unknown_level_is_ignored_rather_than_erroring(client, sample_log):
    body = client.get("/logs", params={"level": "NOPE"}).json()
    assert len(body["records"]) == 5


def test_search_matches_message_or_logger(client, sample_log):
    by_msg = client.get("/logs", params={"q": "distinctive-needle-xyz"}).json()["records"]
    assert len(by_msg) == 1 and by_msg[0]["logger"] == "force_app.backup"

    by_logger = client.get("/logs", params={"q": "force_app.nidaq"}).json()["records"]
    assert len(by_logger) == 1 and by_logger[0]["level"] == "WARNING"

    assert client.get("/logs", params={"q": "NEEDLE-XYZ"}).json()[
        "records"
    ], "search is case-insensitive"


def test_loggers_list_is_reported_for_the_ui(client, sample_log):
    body = client.get("/logs").json()
    assert body["loggers"] == [
        "force_app.backup",
        "force_app.main",
        "force_app.nidaq",
        "force_app.session",
    ]


def test_limit_is_clamped(client, sample_log):
    assert len(client.get("/logs", params={"limit": 99999}).json()["records"]) <= 5000
    assert client.get("/logs", params={"limit": 0}).status_code == 200
    assert len(client.get("/logs", params={"limit": 2}).json()["records"]) == 2


def test_filters_search_the_whole_history_not_just_the_tail(tmp_path, monkeypatch, client):
    """The regression: truncating to `limit` BEFORE filtering hid exactly what was searched for.

    An error early in a long log, with a filter applied, must still be found — that is when
    someone reaches for the level filter in the first place.
    """
    lines = ["2026-08-22 22:00:00,000 ERROR force_app.session: the needle, early on"]
    lines += [f"2026-08-22 22:01:{i:02d},000 INFO force_app.main: filler {i}" for i in range(60)]
    p = tmp_path / "backend.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(main, "LOG_PATH", str(p))

    # A small window: the ERROR is far outside the most recent `limit` lines.
    errs = client.get("/logs", params={"level": "ERROR", "limit": 10}).json()["records"]
    assert len(errs) == 1 and "needle" in errs[0]["message"]

    hits = client.get("/logs", params={"q": "needle", "limit": 10}).json()["records"]
    assert len(hits) == 1

    # Unfiltered still means "the most recent N".
    recent = client.get("/logs", params={"limit": 10}).json()["records"]
    assert len(recent) == 10 and all("filler" in r["message"] for r in recent)


def test_limit_still_caps_filtered_results(tmp_path, monkeypatch, client):
    lines = [f"2026-08-22 22:00:{i:02d},000 ERROR force_app.main: e{i}" for i in range(40)]
    p = tmp_path / "backend.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(main, "LOG_PATH", str(p))

    body = client.get("/logs", params={"level": "ERROR", "limit": 5}).json()
    assert len(body["records"]) == 5
    assert body["truncated"] is True
    assert body["records"][-1]["message"] == "e39"  # the most recent matches are kept
