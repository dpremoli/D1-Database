"""Static catalog of NI C-series / DAQ cards → connector geometry + channel counts.

Drives both the simulated chassis and the "add card" gallery, and gives the real-enumeration path
a connector type per ``product_type`` (nidaqmx reports the model string but not "is this BNC or a
terminal block"). Connector ∈ ``bnc | terminal | dsub``. Unknown models fall back to a generic
terminal card whose analog-input count comes from the live ``ai_physical_chans`` list.
"""

from __future__ import annotations

# connector: how the front panel presents its inputs (drives the virtual view).
#   bnc      — round coax jacks (one per channel)
#   terminal — screw/spring terminal block (numbered pins)
#   dsub     — D-Sub connector (digital / counter, e.g. an encoder tacho)
CATALOG: dict[str, dict] = {
    "NI 9215": {
        "label": "NI 9215",
        "connector": "bnc",
        "ai": 4,
        "ci": 0,
        "vmax": 10.0,
        "ks": 100.0,
        "note": "±10 V simultaneous AI",
    },
    "NI 9234": {
        "label": "NI 9234",
        "connector": "bnc",
        "ai": 4,
        "ci": 0,
        "iepe": True,
        "vmax": 5.0,
        "ks": 51.2,
        "note": "IEPE sound & vibration",
    },
    "NI 9250": {
        "label": "NI 9250",
        "connector": "bnc",
        "ai": 2,
        "ci": 0,
        "iepe": True,
        "vmax": 5.0,
        "ks": 102.4,
        "note": "IEPE, 2-ch",
    },
    "NI 9205": {
        "label": "NI 9205",
        "connector": "terminal",
        "ai": 32,
        "ci": 0,
        "vmax": 10.0,
        "ks": 250.0,
        "note": "spring terminal, 32-ch",
    },
    "NI 9201": {
        "label": "NI 9201",
        "connector": "terminal",
        "ai": 8,
        "ci": 0,
        "vmax": 10.0,
        "ks": 500.0,
        "note": "screw terminal, 8-ch",
    },
    "NI 9401": {
        "label": "NI 9401",
        "connector": "dsub",
        "ai": 0,
        "ci": 8,
        "note": "digital I/O / counter",
    },
    "NI 9411": {
        "label": "NI 9411",
        "connector": "dsub",
        "ai": 0,
        "ci": 6,
        "note": "differential digital (encoder)",
    },
}

# Order shown in the "add card" gallery.
CATALOG_ORDER = ["NI 9215", "NI 9234", "NI 9250", "NI 9205", "NI 9201", "NI 9401", "NI 9411"]

GENERIC = {
    "label": "Generic AI",
    "connector": "terminal",
    "ai": 0,
    "ci": 0,
    "note": "unknown model",
}


def normalize(product_type: str) -> str:
    """Fold 'NI-9215' / 'ni 9215' / 'cDAQ9215' variants onto the catalog key 'NI 9215'."""
    p = (product_type or "").strip().upper().replace("-", " ").replace("_", " ")
    p = " ".join(p.split())
    if p.startswith("NI "):
        p = p[3:]
    digits = "".join(ch for ch in p if ch.isdigit())
    return f"NI {digits}" if digits else (product_type or "")


def lookup(product_type: str, ai_count: int | None = None, ci_count: int | None = None) -> dict:
    """Catalog entry for a model; generic terminal fallback (using the live ai/ci counts)."""
    entry = CATALOG.get(normalize(product_type))
    if entry is not None:
        return dict(entry)
    g = dict(GENERIC, label=product_type or GENERIC["label"])
    if ai_count is not None:
        g["ai"] = int(ai_count)
    if ci_count is not None:
        g["ci"] = int(ci_count)
    return g


def gallery() -> list[dict]:
    """Catalog cards for the add-card picker, in display order."""
    return [dict(CATALOG[k], product_type=k) for k in CATALOG_ORDER]
