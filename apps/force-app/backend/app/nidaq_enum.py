"""Enumerate NI-DAQ hardware into a chassis → modules → ports tree the UI can draw.

Two paths, same JSON shape:
  * real      — walk ``nidaqmx.system.System.local().devices`` (only where the DAQmx runtime
                exists). ``system`` is injectable so the parser is unit-testable with a fake tree.
  * simulated — expand a compact ``[{slot, product_type}]`` layout (persisted, editable via the
                add/remove-card endpoints) into the same tree. Used on dev machines w/o DAQmx.

Port ``physical`` is the exact nidaqmx channel string ("cDAQ1Mod1/ai0") that a task / NidaqSource
consumes, so an assignment maps 1:1 onto acquisition.
"""

from __future__ import annotations

from . import nidaq_catalog as cat

# Compact default simulated rig: an 8-slot cDAQ with two ±10 V AI cards + an IEPE card.
DEFAULT_SIM_LAYOUT = {
    "name": "cDAQ1",
    "product_type": "cDAQ-9178",
    "slots": 8,
    "cards": [
        {"slot": 1, "product_type": "NI 9215"},
        {"slot": 2, "product_type": "NI 9215"},
        {"slot": 3, "product_type": "NI 9234"},
    ],
}


def _ports_for(dev_name: str, entry: dict) -> list[dict]:
    """Synthesise ai0..aiN / ctr0..ctrM ports from a catalog entry's channel counts."""
    ports: list[dict] = []
    for i in range(int(entry.get("ai", 0))):
        ports.append({"id": f"ai{i}", "kind": "ai", "physical": f"{dev_name}/ai{i}"})
    for i in range(int(entry.get("ci", 0))):
        ports.append({"id": f"ctr{i}", "kind": "ci", "physical": f"{dev_name}/ctr{i}"})
    return ports


def _module(dev_name: str, product_type: str, slot: int, ports: list[dict] | None = None) -> dict:
    entry = cat.lookup(product_type)
    return {
        "name": dev_name,
        "product_type": product_type,
        "label": entry.get("label", product_type),
        "slot": int(slot),
        "connector": entry.get("connector", "terminal"),
        "note": entry.get("note", ""),
        "iepe": bool(entry.get("iepe", False)),
        "ports": ports if ports is not None else _ports_for(dev_name, entry),
    }


def enumerate_simulated(layout: dict | None = None) -> dict:
    layout = layout or DEFAULT_SIM_LAYOUT
    modules = []
    for card in sorted(layout.get("cards", []), key=lambda c: int(c["slot"])):
        slot = int(card["slot"])
        name = f"{layout['name']}Mod{slot}"
        modules.append(_module(name, card["product_type"], slot))
    chassis = {
        "name": layout.get("name", "cDAQ1"),
        "product_type": layout.get("product_type", "cDAQ-9178"),
        "slots": int(layout.get("slots", 8)),
        "modules": modules,
    }
    return {"simulated": True, "chassis": [chassis], "standalone": []}


def _ports_from_names(names, kind: str) -> list[dict]:
    return [{"id": n.split("/")[-1], "kind": kind, "physical": n} for n in names]


def _chan_names(collection) -> list[str]:
    out = []
    for ch in collection or []:
        out.append(getattr(ch, "name", str(ch)))
    return out


def enumerate_real(system) -> dict:
    """Parse a live (or faked) nidaqmx System into the tree. Defensive: DAQmx property access can
    raise per-device, so every read is guarded and a bad device is skipped rather than fatal."""
    chassis_by_name: dict[str, dict] = {}
    modules_by_chassis: dict[str, list[dict]] = {}
    standalone: list[dict] = []

    devices = list(getattr(system, "devices", []) or [])
    # First pass: identify chassis (they own module devices).
    for dev in devices:
        mods = _safe(lambda: list(dev.chassis_module_devices), [])
        if mods:
            chassis_by_name[dev.name] = {
                "name": dev.name,
                "product_type": _safe(lambda: dev.product_type, "cDAQ"),
                "slots": len(mods) or 8,
                "modules": [],
            }
            modules_by_chassis.setdefault(dev.name, [])

    # Second pass: place each non-chassis device as a module or a standalone device.
    for dev in devices:
        if dev.name in chassis_by_name:
            continue
        product_type = _safe(lambda: dev.product_type, "")
        ai = _ports_from_names(_chan_names(_safe(lambda: dev.ai_physical_chans, [])), "ai")
        ci = _ports_from_names(_chan_names(_safe(lambda: dev.ci_physical_chans, [])), "ci")
        ports = ai + ci
        chassis = _safe(lambda: dev.compact_daq_chassis_device, None)
        slot = _safe(lambda: dev.compact_daq_slot_num, 0)
        if chassis is not None and getattr(chassis, "name", None) in chassis_by_name:
            modules_by_chassis[chassis.name].append(
                _module(dev.name, product_type, slot, ports=ports)
            )
        else:
            standalone.append(_module(dev.name, product_type, slot or 0, ports=ports))

    for name, mods in modules_by_chassis.items():
        chassis_by_name[name]["modules"] = sorted(mods, key=lambda m: m["slot"])
    return {
        "simulated": False,
        "chassis": list(chassis_by_name.values()),
        "standalone": standalone,
    }


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def enumerate_devices(sim_layout: dict | None = None, system=None) -> dict:
    """Real enumeration when a DAQmx System is available/importable, else simulated."""
    if system is not None:
        return enumerate_real(system)
    sysobj = _local_system()
    if sysobj is not None and list(getattr(sysobj, "devices", []) or []):
        return enumerate_real(sysobj)
    return enumerate_simulated(sim_layout)


def _local_system():
    try:
        from nidaqmx.system import System

        return System.local()
    except Exception:
        return None
