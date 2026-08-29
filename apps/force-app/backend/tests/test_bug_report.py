"""Bug-report issue body assembly (apps/force-app/backend/app/bug_report.py)."""

from app.bug_report import build_body

BASE = {
    "description": "RPM looked wrong",
    "app_version": "0.1.17",
    "platform": "Win32",
    "route": "/record",
    "reporter_email": "someone@example.com",
    "log_tail": "",
}


def test_body_includes_the_basics():
    body = build_body(**BASE)
    assert "RPM looked wrong" in body
    assert "0.1.17" in body
    assert "`/record`" in body
    assert "someone@example.com" in body


def test_diagnostics_are_rendered_uncollapsed():
    """Machine state is short and answers the first questions a triager would ask, so it is not
    hidden behind a <details> the way the long log tails are."""
    body = build_body(**{**BASE, "diagnostics": "labamp: mock=True mode=MEASURE"})
    assert "Machine state at time of report" in body
    assert "labamp: mock=True mode=MEASURE" in body
    head, _, tail = body.partition("labamp: mock=True")
    assert "<details>" not in head, "diagnostics must not be collapsed"


def test_console_and_log_tails_are_collapsed_separately():
    body = build_body(
        **{**BASE, "log_tail": "backend line", "console_tail": "console line"},
    )
    assert body.count("<details>") == 2
    assert "Renderer console" in body and "Recent backend log" in body
    assert "console line" in body and "backend line" in body


def test_absent_sections_are_omitted_entirely():
    body = build_body(**BASE)
    assert "<details>" not in body
    assert "Machine state" not in body


def test_backticks_in_attached_text_cannot_break_out_of_the_fence():
    """The tails are renderer- and machine-supplied. A literal ``` would close our fence early and
    let whatever follows render as raw markdown/HTML in the issue."""
    hostile = "before ``` after"
    body = build_body(**{**BASE, "log_tail": hostile, "console_tail": hostile})
    assert "before ``` after" not in body
    # Exactly the fences we opened: two per collapsed section, and none contributed by the payload.
    assert body.count("```") == 4


def test_long_tails_are_truncated_from_the_front():
    """GitHub caps issue bodies, and the END of a log is the part that matters."""
    body = build_body(**{**BASE, "log_tail": "X" * 50_000 + "TAIL_MARKER"})
    assert "TAIL_MARKER" in body
    assert len(body) < 30_000
