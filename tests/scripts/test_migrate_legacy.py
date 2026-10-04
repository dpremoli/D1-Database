"""scripts/migrate_legacy.py: pure helpers (findings 7.4-7.7) and, with DATABASE_URL pointing at
a migrated database, DB-level behaviour. DB tests run inside a transaction that is rolled back.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

pytest.importorskip("openpyxl")
pytest.importorskip("psycopg2")

import migrate_legacy as ml  # noqa: E402

# ---- clean_str (7.5) ------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["Na", " Na ", "Ti", "Nb", "Namibia"])
def test_clean_str_keeps_sodium_and_ordinary_values(raw):
    assert ml.clean_str(raw) == raw.strip()


@pytest.mark.parametrize(
    "raw", [None, "", "  ", "none", "None", "N/A", "n/a", "na", "NA"]
)
def test_clean_str_drops_null_tokens(raw):
    assert ml.clean_str(raw) is None


# ---- clean_float (7.7) -----------------------------------------------------------------


def test_clean_float_keeps_zero():
    assert ml.clean_float(0) == 0.0
    assert ml.clean_float("0.0") == 0.0
    assert ml.clean_float(0.0) is not None


@pytest.mark.parametrize("raw", [None, "", "abc", "n/a"])
def test_clean_float_none_for_blank_or_garbage(raw):
    assert ml.clean_float(raw) is None


def test_clean_float_parses_numbers():
    assert ml.clean_float("2.5") == 2.5
    assert ml.clean_float(3) == 3.0


# ---- sodium survives into the alloying-element junction (7.5) ----------------------------


class _Cur:
    def __init__(self, rows):
        self.rows = rows
        self.q = ""

    def execute(self, sql, params=None):
        self.q = sql

    def fetchall(self):
        return self.rows


def test_sodium_is_not_dropped_from_alloying_elements(monkeypatch):
    captured = {}

    def fake_execute_values(cur, sql, data, **kw):
        captured["sql"], captured["data"] = sql, list(data)

    monkeypatch.setattr(ml.psycopg2.extras, "execute_values", fake_execute_values)

    class Cur(_Cur):
        def execute(self, sql, params=None):
            self.q = sql

        def fetchall(self):
            if "FROM alloying_elements" in self.q:
                return [("Na",), ("Al",), ("Ti",)]
            return [("X1", "11111111-1111-1111-1111-111111111111")]

    n = ml.load_material_elements(
        Cur([]), [{"Code": "X1", "Alloying Elements": "Na, Al, n/a, na, Ti"}], dry=False
    )
    assert n == 3
    assert sorted(sym for _m, sym in captured["data"]) == ["Al", "Na", "Ti"]


# ---- upserts never overwrite live values (7.7) -------------------------------------------


def _upserts():
    src = open(ml.__file__, encoding="utf-8").read()
    blocks = []
    for stmt in re.findall(r'"""\s*INSERT INTO.*?"""', src, flags=re.S):
        m = re.search(r"DO UPDATE SET(.*)\"\"\"$", stmt, flags=re.S)
        if m:
            blocks.append(m.group(1))
    return blocks


def test_every_do_update_assignment_keeps_the_existing_value():
    blocks = _upserts()
    assert blocks, "no upserts found"
    for block in blocks:
        for assignment in re.split(r",\s+(?=\w+\s*=)", " ".join(block.split())):
            m = re.match(r"\s*(\w+)\s*=\s*(.*)", assignment, flags=re.S)
            assert m, assignment
            col, rhs = m.groups()
            rhs = " ".join(rhs.split())
            assert re.match(
                rf"COALESCE\((\w+)\.{col},\s*EXCLUDED\.{col}\)$", rhs
            ), f"{col} = {rhs} may overwrite an existing value"


def test_module_docstring_matches_the_rerun_behaviour():
    assert "never overwrites" in ml.__doc__
