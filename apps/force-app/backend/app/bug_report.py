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


def build_body(
    *,
    description: str,
    app_version: str,
    platform: str,
    route: str,
    reporter_email: str,
    log_tail: str,
) -> str:
    parts = [
        description.strip() or "_(no description provided)_",
        "",
        "---",
        f"**App version:** {app_version or 'unknown'}  ",
        f"**Platform:** {platform or 'unknown'}  ",
        f"**Route at time of report:** `{route or 'unknown'}`  ",
    ]
    if reporter_email:
        parts.append(f"**Reported by:** {reporter_email}  ")
    if log_tail.strip():
        # <details> keeps a long tail from burying the description in the GitHub UI, while still
        # making it one click away instead of a separate download. The log tail is renderer-
        # controlled text, so a literal ``` sequence in it would otherwise close our fence early
        # and let the rest of the tail render as raw markdown/HTML in the issue body — break up
        # any run of backticks with a zero-width space so it can't.
        safe_tail = log_tail.strip()[-8000:].replace(
            "```", "`​`​`"
        )  # GitHub issue bodies cap at 65536 chars; leave headroom
        parts += [
            "",
            "<details><summary>Recent backend log (auto-attached)</summary>",
            "",
            "```",
            safe_tail,
            "```",
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
) -> dict:
    """Returns {"ok": True, "url": ...} or {"ok": False, "reason": ...}. Never raises."""
    title = title.strip()
    if not title:
        return {"ok": False, "reason": "A title is required."}

    body = build_body(
        description=description,
        app_version=app_version,
        platform=platform,
        route=route,
        reporter_email=reporter_email,
        log_tail=log_tail,
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.post(
                f"{_relay_url()}/report",
                json={"title": title[:250], "body": body, "labels": ["force-app", "in-app-report"]},
            )
    except httpx.HTTPError as e:
        return {"ok": False, "reason": f"could not reach the bug-report relay: {e}"}

    if res.status_code >= 300:
        return {"ok": False, "reason": f"bug-report relay error (HTTP {res.status_code})"}

    return res.json()
