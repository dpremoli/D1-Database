import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

pytest.importorskip("psycopg2")
pytest.importorskip("requests")

from force_orchestrator import _layer_fingerprint


def test_fingerprint_is_stable_and_order_independent():
    a = [
        {"name": "chuck", "role": "mask", "version": 2},
        {"name": "edge", "role": "label", "version": 1},
    ]
    assert _layer_fingerprint(a) == _layer_fingerprint(list(reversed(a)))


def test_fingerprint_changes_with_version():
    a = [{"name": "chuck", "role": "mask", "version": 1}]
    c = [{"name": "chuck", "role": "mask", "version": 2}]
    assert _layer_fingerprint(a) != _layer_fingerprint(c)


def test_fingerprint_changes_when_a_layer_is_added():
    a = [{"name": "chuck", "role": "mask", "version": 1}]
    b = a + [{"name": "edge", "role": "label", "version": 1}]
    assert _layer_fingerprint(a) != _layer_fingerprint(b)


def test_fingerprint_empty_is_falsy():
    assert not _layer_fingerprint([])
    assert not _layer_fingerprint(None)
