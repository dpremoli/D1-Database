#!/usr/bin/env python3
"""NL->SQL evaluation harness.

Two modes:

  offline (default)
      Validate every curated gold SQL through the production SQL guard. This is
      a regression test: if the allow-list or guard changes such that a known-
      good analyst query would now be rejected, this fails. Needs no Ollama, no
      database — runs in CI via tests/test_eval_golds.py.

  live (--live)
      For each question, call the running plugin's POST /api/ask, then report
      whether the model produced SQL the guard accepted and the database
      executed. Semantic correctness is for a human to judge from the printed
      SQL; this measures the safe-and-runnable rate. Requires LLM_API_URL (and
      WORKER_WEBHOOK_SECRET if the endpoint is secured).

Usage:
    python eval/run_eval.py              # offline gold validation
    python eval/run_eval.py --live       # hit a running plugin
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Make `app` importable when run from the plugin root or this directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.lib.sql_guard import SqlGuardError, validate  # noqa: E402

QUESTIONS_PATH = Path(__file__).resolve().parent / "questions.json"


def load_questions() -> list[dict]:
    return json.loads(QUESTIONS_PATH.read_text())


def run_offline(questions: list[dict]) -> int:
    """Guard every gold SQL. Returns process exit code."""
    failures = 0
    for q in questions:
        try:
            validate(q["gold_sql"])
            print(f"  PASS  {q['id']}")
        except SqlGuardError as exc:
            failures += 1
            print(f"  FAIL  {q['id']}: {exc}")
    passed = len(questions) - failures
    print(f"\noffline gold validation: {passed} passed, {failures} failed")
    return 1 if failures else 0


def run_live(questions: list[dict]) -> int:
    import requests

    api_url = os.environ["LLM_API_URL"].rstrip("/")
    headers = {}
    secret = os.getenv("WORKER_WEBHOOK_SECRET")
    if secret:
        headers["X-Worker-Secret"] = secret

    ok = 0
    for q in questions:
        resp = requests.post(
            f"{api_url}/api/ask",
            json={"question": q["question"]},
            headers=headers,
            timeout=180,
        )
        if resp.status_code == 200:
            ok += 1
            body = resp.json()
            print(f"  RUN   {q['id']}: {body.get('sql', '').strip()[:120]}")
        else:
            print(f"  REJECT {q['id']}: {resp.status_code} {resp.text[:160]}")
    print(f"\nlive run: {ok}/{len(questions)} produced safe, runnable SQL")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="hit a running plugin")
    args = parser.parse_args()

    questions = load_questions()
    print(f"Loaded {len(questions)} evaluation questions.\n")
    return run_live(questions) if args.live else run_offline(questions)


if __name__ == "__main__":
    raise SystemExit(main())
