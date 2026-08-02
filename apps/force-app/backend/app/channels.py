"""The arbitrary channel model: named channels with a role, optionally bound to a physical NI-DAQ
input. Roles drive the force maths (all ``Fx`` channels sum into Fx, etc.); ``Tacho`` marks the
speed input; ``Aux`` is recorded but not summed. ``source="virtual"`` channels have no physical
binding yet (bindable later). This slice persists the model + bridges it to the existing recorder's
fixed [Fx1,Fx2,Fy1,Fy2,Fz1,Fz2,Fz3,Fz4,Tacho] layout; variable columns are a later slice.
"""

from __future__ import annotations

from .config import DEFAULT_NIDAQ_CHANNELS, DYNO_CHANNELS, TACHO_CHANNEL

ROLES = ["Fx", "Fy", "Fz", "Tacho", "Aux"]
ROLE_COLOR = {
    "Fx": "#f87171",
    "Fy": "#4ade80",
    "Fz": "#60a5fa",
    "Tacho": "#c084fc",
    "Aux": "#fbbf24",
    "Virtual": "#38bdf8",
}
# Force-first default: the first 8 analog inputs become these named channels, in this order.
FORCE_ORDER = list(DYNO_CHANNELS)  # Fx1 Fx2 Fy1 Fy2 Fz1 Fz2 Fz3 Fz4
_ROLE_OF = {n: n[:2] for n in FORCE_ORDER}  # "Fx1" -> "Fx"


def make_channel(
    name: str,
    role: str,
    physical: str | None = None,
    sensitivity: float | None = None,
    gain: float | None = None,
    source: str = "hardware",
) -> dict:
    return {
        "name": name,
        "role": role,
        "physical": physical,
        "sensitivity_pc_per_n": sensitivity,
        "gain_n_per_v": gain,
        "source": source,
        "color": ROLE_COLOR.get("Virtual" if source == "virtual" else role, "#94a3b8"),
    }


def _ai_ports(devices: dict) -> list[str]:
    """All analog-input physical channel strings, chassis order then slot order."""
    out: list[str] = []
    for ch in devices.get("chassis", []):
        for mod in ch.get("modules", []):
            for p in mod.get("ports", []):
                if p.get("kind") == "ai":
                    out.append(p["physical"])
    for mod in devices.get("standalone", []):
        for p in mod.get("ports", []):
            if p.get("kind") == "ai":
                out.append(p["physical"])
    return out


def autoassign(devices: dict) -> list[dict]:
    """Force-first: fill Fx1..Fz4 across the first 8 AI, then Tacho on the next AI (ai0 of the next
    module when the force channels take whole 4-ch cards). Remaining ports left unassigned."""
    ai = _ai_ports(devices)
    channels: list[dict] = []
    for i, name in enumerate(FORCE_ORDER):
        phys = ai[i] if i < len(ai) else None
        channels.append(make_channel(name, _ROLE_OF[name], physical=phys))
    tacho_phys = ai[8] if len(ai) > 8 else None  # ai0 of the next module
    channels.append(make_channel(TACHO_CHANNEL, "Tacho", physical=tacho_phys))
    return channels


def to_record_channels(channels: list[dict]) -> list[str]:
    """Ordered physical list for the recorder's fixed [Fx1..Fz4, Tacho] layout. Unbound slots keep
    the placeholder default so a partial config still starts."""
    by_name = {c["name"]: c for c in channels}
    order = FORCE_ORDER + [TACHO_CHANNEL]
    out: list[str] = []
    for i, name in enumerate(order):
        c = by_name.get(name)
        phys = c.get("physical") if c else None
        out.append(phys or DEFAULT_NIDAQ_CHANNELS[i])
    return out


def dyno_gains(channels: list[dict]) -> list[float]:
    """Per-channel N/V gains for the 8 dyno channels, if the config supplies them (else empty →
    the recorder derives gains from the amp ranges as before)."""
    by_name = {c["name"]: c for c in channels}
    gains = [by_name.get(n, {}).get("gain_n_per_v") for n in FORCE_ORDER]
    return [float(g) for g in gains] if all(g is not None for g in gains) else []
