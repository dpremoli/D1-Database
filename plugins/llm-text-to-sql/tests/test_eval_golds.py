"""Every curated gold query in eval/questions.json must pass the SQL guard.

This keeps the evaluation set honest: if the guard or allow-list changes such
that a known-good analyst query would now be rejected, CI fails here.
"""

import json
from pathlib import Path

import pytest

from app.lib.sql_guard import validate

_QUESTIONS = json.loads(
    (Path(__file__).resolve().parent.parent / "eval" / "questions.json").read_text()
)


@pytest.mark.parametrize("item", _QUESTIONS, ids=[q["id"] for q in _QUESTIONS])
def test_gold_sql_passes_guard(item):
    validate(item["gold_sql"])  # must not raise


def test_questions_have_required_fields():
    for q in _QUESTIONS:
        assert q["id"] and q["question"] and q["gold_sql"]
