"""Files a GitHub issue from inside the app, via the bug-report relay on d1-server.

No machine running this backend holds a GitHub credential — a packaged build's asar is trivially
extractable, so any token shipped to an acquisition PC would effectively be public. Instead the
relay (apps/force-app/bug-report-relay), reachable only over Tailscale, holds a GitHub App private
key centrally and mints short-lived tokens on request. Configure via env vars:

    FORCE_APP_BUG_REPORT_RELAY_URL   base URL of the relay, e.g.
                                      https://d1-server.tail54eeb6.ts.net/bug-report-relay

Reporting is considered configured whenever a relay URL is set — the relay itself reports back
"not configured" if the GitHub App credentials aren't set up on its end, which callers should
surface as-is.
"""

from __future__ import annotations

import os

import httpx

DEFAULT_RELAY_URL = "https://d1-server.tail54eeb6.ts.net/bug-report-relay"


def _relay_url() -> str:
    return os.environ.get("FORCE_APP_BUG_REPORT_RELAY_URL", DEFAULT_RELAY_URL)


def configured() -> bool:
    return bool(_relay_url())


def _fence(text: str, limit: int) -> list[str]:
    """A fenced block of renderer/host-supplied text, tail-truncated and made fence-safe.

    The text is not trusted: a literal ``` inside it would close our fence early and let the rest
    render as raw markdown/HTML in the issue body, so any run of backticks is broken up with a
    zero-width space.
    """
    return ["```", text.strip()[-limit:].replace("```", "`​`​`"), "```"]


KIND_LABELS = {"bug": "bug", "feature": "enhancement"}
KIND_PREFIXES = {"bug": "[Bug]", "feature": "[Feature]"}

# Mirrors the app's real sections (see web/src/router.ts) plus "gui" for cross-cutting UI/layout
# issues not tied to one page, and "general" as the catch-all. Kept as a fixed set (not whatever
# string a client sends) so the resulting `area:*` label is always one of these, never freeform —
# the whole point is a stable set of labels to filter/catalogue by later.
AREAS = {"gui", "recording", "plotting", "diagnostics", "settings", "labamp", "nidaq", "general"}


def build_body(
    *,
    description: str,
    app_version: str,
    platform: str,
    route: str,
    reporter_email: str,
    log_tail: str,
    diagnostics: str = "",
    console_tail: str = "",
) -> str:
    parts = [
        description.strip() or "_(no description provided)_",
        "",
        "---",
        f"**App version:** {app_version or 'unknown'}  ",
        f"**Platform:** {platform or 'unknown'}  ",
        f"**Route at time of report:** `{route or 'unknown'}`  ",
        # Always present, never silently dropped — a triager should never have to guess whether a
        # missing line here means "not signed in" or "the client forgot to send it".
        f"**Reported by:** {reporter_email or '_not signed in_'}  ",
    ]
    # Machine state first: it is short, and it answers the questions that otherwise cost a
    # round-trip with the operator ("is the amp in real or mock mode?", "which DAQ is attached?",
    # "was it actually recording?"). Not collapsed, unlike the two long tails below.
    if diagnostics.strip():
        parts += ["", "**Machine state at time of report**", "", *_fence(diagnostics, 6000)]
    if console_tail.strip():
        parts += [
            "",
            "<details><summary>Renderer console (auto-attached)</summary>",
            "",
            *_fence(console_tail, 8000),
            "</details>",
        ]
    if log_tail.strip():
        # <details> keeps a long tail from burying the description in the GitHub UI, while still
        # making it one click away instead of a separate download. GitHub issue bodies cap at
        # 65536 chars; the per-section limits here leave headroom for all three tails together.
        parts += [
            "",
            "<details><summary>Recent backend log (auto-attached)</summary>",
            "",
            *_fence(log_tail, 20000),
            "</details>",
        ]
    return "\n".join(parts)


async def create_issue(
    *,
    title: str,
    description: str,
    app_version: str,
    platform: str,
    route: str,
    reporter_email: str,
    log_tail: str,
    diagnostics: str = "",
    console_tail: str = "",
    kind: str = "bug",
    area: str = "general",
) -> dict:
    """Returns {"ok": True, "url": ...} or {"ok": False, "reason": ...}. Never raises."""
    title = title.strip()
    if not title:
        return {"ok": False, "reason": "A title is required."}
    kind = kind if kind in KIND_LABELS else "bug"
    area = area if area in AREAS else "general"
    prefix = KIND_PREFIXES[kind]
    # Tag by prefix, not by trusting any "[Bug]"/"[Feature]" the reporter typed themselves — the
    # picker is the single source of truth so the title prefix and the label can never disagree.
    if not title.startswith(prefix):
        title = f"{prefix} {title}"

    body = build_body(
        description=description,
        app_version=app_version,
        platform=platform,
        route=route,
        reporter_email=reporter_email,
        log_tail=log_tail,
        diagnostics=diagnostics,
        console_tail=console_tail,
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.post(
                f"{_relay_url()}/report",
                json={
                    "title": title[:250],
                    "body": body,
                    "labels": ["force-app", "in-app-report", KIND_LABELS[kind], f"area:{area}"],
                },
            )
    except httpx.HTTPError as e:
        return {"ok": False, "reason": f"could not reach the bug-report relay: {e}"}

    if res.status_code >= 300:
        return {"ok": False, "reason": f"bug-report relay error (HTTP {res.status_code})"}

    return res.json()


async def list_issues() -> dict:
    """Returns {"ok": True, "issues": [...]} or {"ok": False, "reason": ...}. Never raises."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.get(f"{_relay_url()}/issues")
    except httpx.HTTPError as e:
        return {"ok": False, "reason": f"could not reach the bug-report relay: {e}"}

    if res.status_code >= 300:
        return {"ok": False, "reason": f"bug-report relay error (HTTP {res.status_code})"}

    return res.json()
