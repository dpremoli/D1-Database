"""The TypeScript client transcribes each step's registry contract so it can validate a
recipe before posting it. A transcription drifts silently: the panel would accept a recipe
the service refuses (back to raw 422s), or reject one that would have run.

These tests parse the TS source and compare it against the live Python registry. They are the
reason `recipeChannels.ts` is allowed to hold a hand-written copy of `requires`/`produces`.
"""

from __future__ import annotations


import os
import re

import pytest

from diag import ops as _ops  # noqa: F401  -- registration side effects
from diag.registry import SEED_COLUMNS, STEPS

_TS = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "packages", "force-plotting", "src", "recipeChannels.ts",
)


_HELP_TS = os.path.join(os.path.dirname(_TS), "diagHelp.ts")


def _ts_source() -> str:
    with open(os.path.abspath(_TS), encoding="utf-8") as fh:
        return fh.read()


def _help_source() -> str:
    with open(os.path.abspath(_HELP_TS), encoding="utf-8") as fh:
        return fh.read()


def _parse_object_of_string_arrays(src: str, name: str) -> dict[str, list[str]]:
    """Pull `const <name>: Record<string, string[]> = { op: ['a', 'b'], ... }` out of the TS."""
    m = re.search(rf"const {name}[^=]*=\s*\{{(.*?)\n\}};", src, re.S)
    assert m, f"{name} not found in recipeChannels.ts"
    out: dict[str, list[str]] = {}
    for op, body in re.findall(r"(\w+):\s*\[([^\]]*)\]", m.group(1)):
        out[op] = [v for v in re.findall(r"'([^']*)'", body)]
    return out


def _op_blocks(src: str, const_name: str, ops) -> dict[str, str]:
    """Split a `Record<op, {...}>` TS literal into one text block per op.

    Split on the `\\n\\t<op>:` keys rather than brace-matching: entries range from a one-line
    `tsa: { ... },` to a multi-line block, and a naive non-greedy `{...}\\n\\t},` match runs
    a short entry into its neighbour (which silently attributed radial_detrend's params to tsa).
    """
    m = re.search(rf"(?:export )?const {const_name}[^=]*=\s*\{{(.*)\n\}};", src, re.S)
    assert m, f"{const_name} not found"
    body = m.group(1)
    starts = sorted(
        (mm.start(), mm.group(1))
        for mm in re.finditer(r"\n\t(\w+):\s*\{", body)
        if mm.group(1) in ops
    )
    out: dict[str, str] = {}
    for i, (pos, op) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(body)
        out[op] = body[pos:end]
    return out


def test_ts_step_requires_matches_the_python_registry():
    ts = _parse_object_of_string_arrays(_ts_source(), "STEP_REQUIRES")
    py = {name: list(spec.requires) for name, spec in STEPS.items()}
    assert set(ts) == set(py), (
        f"ops only in TS: {sorted(set(ts) - set(py))}; "
        f"ops only in Python: {sorted(set(py) - set(ts))}"
    )
    for op in sorted(py):
        assert ts[op] == py[op], f"{op}.requires: TS {ts[op]} != Python {py[op]}"


def test_ts_step_meta_produces_matches_the_python_registry():
    blocks = _op_blocks(_ts_source(), "STEP_META", set(STEPS))
    py = {name: list(spec.produces) for name, spec in STEPS.items()}
    assert set(blocks) == set(py)
    for op in sorted(py):
        got = re.findall(r"'([^']*)'", re.search(r"produces:\s*\[([^\]]*)\]", blocks[op]).group(1))
        assert got == py[op], f"{op}.produces: TS {got} != Python {py[op]}"


def test_ts_seed_columns_match():
    src = _ts_source()
    m = re.search(r"const SEED_COLUMNS = \[([^\]]*)\]", src)
    assert m, "SEED_COLUMNS not found"
    assert re.findall(r"'([^']*)'", m.group(1)) == list(SEED_COLUMNS)


def test_ts_step_tiers_match_the_python_registry():
    blocks = _op_blocks(_ts_source(), "STEP_META", set(STEPS))
    ts = {op: re.search(r"tier:\s*'(\w+)'", b).group(1) for op, b in blocks.items()}
    assert ts == {name: spec.tier for name, spec in STEPS.items()}


@pytest.mark.parametrize("op", sorted(STEPS))
def test_every_registered_step_has_client_help(op):
    """A step with no help text renders a bare op name in the panel -- the exact opacity the
    workbench is meant to remove. Fail loudly when a new step skips its description."""
    assert op in _op_blocks(_help_source(), "STEP_HELP", set(STEPS)), \
        f"no STEP_HELP entry for {op!r}"


def test_every_tunable_param_has_help():
    """Each param the panel renders an input for must have a sentence explaining it. The
    field report that prompted this ('changed HDBSCAN to 3 clusters and it still shows many')
    was a param whose label meant something other than what it read as."""
    meta = _op_blocks(_ts_source(), "STEP_META", set(STEPS))
    help_blocks = _op_blocks(_help_source(), "STEP_HELP", set(STEPS))
    missing = []
    for op, block in meta.items():
        keys = re.findall(r"key:\s*'(\w+)'", block)
        documented = set(re.findall(r"(\w+):\s*$|(\w+):\s*'", help_blocks.get(op, "")))
        documented = {a or b for a, b in documented}
        documented |= set(re.findall(r"\n\t\t\t(\w+):", help_blocks.get(op, "")))
        missing.extend(f"{op}.{k}" for k in keys if k not in documented)
    assert not missing, f"params with no help text: {missing}"
