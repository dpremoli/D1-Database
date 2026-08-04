"""Kistler LabAmp (5167A8x / STAR-LabAmp) REST client — slice 2c. Mirrors the MATLAB app's
`%% Kistler DAQ API calls` and the vendor docs in docs/hardware/kistler-labamp/.

Transport: POST http://<ampIP>/api/… with a JSON body; responses are {"result":0,"data":{…}}
(result == 0 = success). The amp is link-local, reachable only from the acquisition PC, so this runs
on the backend (not the browser). A MockLabAmp with the same interface lets the UI be exercised
without hardware; the real client is validated on the rig.
"""

from __future__ import annotations

from typing import Protocol

import httpx

# Sensor parameter leaves read for the per-channel table (as in the MATLAB generateTableData).
SENSOR_LEAVES = ["name", "serialNumber", "physicalQuantity", "sensitivity", "range"]


class LabAmpError(Exception):
    pass


class LabAmp(Protocol):
    base_url: str
    mock: bool

    def ping(self) -> bool: ...
    def get_operation_mode(self) -> str | None: ...
    def set_operation_mode(self, mode: str) -> None: ...
    def sensor_table(self, channels: int) -> list[dict]: ...
    def export_params(self) -> dict: ...
    def signal_get(self, channels: list[int]) -> list[dict]: ...
    def set_range(self, channel: int, value: float) -> None: ...
    def channel_status(self, channels: int) -> dict[int, str]: ...


class LabAmpClient:
    """Real HTTP client against a physical LabAmp."""

    def __init__(
        self, base_url: str, timeout: float = 10.0, transport: httpx.BaseTransport | None = None
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.mock = False
        self._transport = transport  # injectable for tests (httpx.MockTransport)

    def _post(self, path: str, body: dict) -> dict:
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport) as c:
                r = c.post(f"{self.base_url}{path}", json=body)
        except httpx.HTTPError as e:
            raise LabAmpError(f"LabAmp unreachable at {self.base_url}: {e}") from e
        if r.status_code != 200:
            raise LabAmpError(f"LabAmp HTTP {r.status_code} for {path}")
        try:
            j = r.json()
        except ValueError as e:
            raise LabAmpError(f"LabAmp non-JSON response for {path}") from e
        if j.get("result", 0) != 0:
            raise LabAmpError(f"LabAmp error result={j.get('result')} for {path}")
        return j.get("data", {})

    def ping(self) -> bool:
        try:
            self.get_operation_mode()
            return True
        except LabAmpError:
            return False

    def get_operation_mode(self) -> str | None:
        data = self._post("/api/$/operationMode/get", {})
        return data.get("mode")

    def set_operation_mode(self, mode: str) -> None:
        if mode not in ("MEASURE", "RESET"):
            raise LabAmpError(f"invalid mode {mode!r}")
        self._post("/api/$/operationMode/set", {"mode": mode})

    def get_params(self, paths: list[str]) -> dict[str, object]:
        data = self._post("/api/param/get", {"params": paths})
        # Response carries a list of {name, value} pairs (per the MATLAB parser).
        out: dict[str, object] = {}
        for p in data.get("params", []):
            if isinstance(p, dict) and "name" in p:
                out[p["name"]] = p.get("value")
        return out

    def set_params(self, values: dict[str, object]) -> None:
        self._post(
            "/api/param/set", {"params": [{"name": k, "value": v} for k, v in values.items()]}
        )

    def sensor_table(self, channels: int) -> list[dict]:
        paths = [f"/sensor/{i}/{leaf}" for i in range(1, channels + 1) for leaf in SENSOR_LEAVES]
        vals = self.get_params(paths)
        rows = []
        for i in range(1, channels + 1):
            rows.append(
                {"channel": i, **{leaf: vals.get(f"/sensor/{i}/{leaf}") for leaf in SENSOR_LEAVES}}
            )
        return rows

    def export_params(self) -> dict:
        return self._post("/api/param/export", {})

    def signal_get(self, channels: list[int]) -> list[dict]:
        data = self._post("/api/$/signal/get", {"type": "SENSOR", "channels": channels})
        return data.get("items", [])

    def set_range(self, channel: int, value: float) -> None:
        self.set_params({f"/sensor/{channel}/range": value})

    def channel_status(self, channels: int) -> dict[int, str]:
        """Per-channel status (OK / OR_ADC / OR_INPUT …) via /api/$/status/channel."""
        data = self._post(
            "/api/$/status/channel", {"type": "SENSOR", "channels": list(range(1, channels + 1))}
        )
        out: dict[int, str] = {}
        for it in data.get("items", data.get("channels", [])):
            if isinstance(it, dict) and "channel" in it:
                out[int(it["channel"])] = str(it.get("status", "OK"))
        return out


class MockLabAmp:
    """In-memory stand-in returning realistic canned data, so the UI works without hardware."""

    # Per-channel simulated cut peaks (N) so the auto-range demo is realistic (Fx/Fy sub-channels
    # ~40 N, Fz sub-channels ~90 N). Default ranges start deliberately over-ranged (10000 N).
    _PEAKS = {1: 41.0, 2: 39.0, 3: 55.0, 4: 53.0, 5: 92.0, 6: 88.0, 7: 90.0, 8: 91.0}

    def __init__(self, base_url: str = "mock://labamp"):
        self.base_url = base_url
        self.mock = True
        self._mode = "RESET"
        self._ranges: dict[int, float] = {i: 10000.0 for i in range(1, 9)}

    def ping(self) -> bool:
        return True

    def get_operation_mode(self) -> str | None:
        return self._mode

    def set_operation_mode(self, mode: str) -> None:
        if mode not in ("MEASURE", "RESET"):
            raise LabAmpError(f"invalid mode {mode!r}")
        self._mode = mode

    def sensor_table(self, channels: int) -> list[dict]:
        # A plausible 8-channel Kistler multi-component dynamometer layout.
        quant = {1: "Fx", 2: "Fx", 3: "Fy", 4: "Fy", 5: "Fz", 6: "Fz", 7: "Fz", 8: "Fz"}
        sens = {1: -7.87, 2: -7.87, 3: -7.87, 4: -7.87, 5: -3.71, 6: -3.71, 7: -3.71, 8: -3.71}
        rows = []
        for i in range(1, channels + 1):
            rows.append(
                {
                    "channel": i,
                    "name": f"Dyno-{quant.get(i, 'F')}{i}",
                    "serialNumber": f"KIS{4200 + i}",
                    "physicalQuantity": "Force",
                    "sensitivity": sens.get(i, -5.0),
                    "range": self._ranges.get(i, 10000.0),
                }
            )
        return rows

    def export_params(self) -> dict:
        return {
            "device": {"model": "5167A81", "firmware": "1.2.5 (mock)"},
            "operationMode": self._mode,
            "ranges": dict(self._ranges),
        }

    def signal_get(self, channels: list[int]) -> list[dict]:
        out = []
        for ch in channels:
            pk = self._PEAKS.get(ch, 50.0)
            out.append(
                {
                    "channel": ch,
                    "live": [round(0.6 * pk, 3)],
                    "max": [pk],
                    "min": [-pk],
                    "rms": [round(0.5 * pk, 3)],
                    "type": "SENSOR",
                }
            )
        return out

    def set_range(self, channel: int, value: float) -> None:
        self._ranges[int(channel)] = float(value)

    def set_params(self, values: dict) -> None:
        for k, v in values.items():
            if k.startswith("/sensor/") and k.endswith("/range"):
                self._ranges[int(k.split("/")[2])] = float(v)

    def channel_status(self, channels: int) -> dict[int, str]:
        # OR_INPUT if the (simulated) peak exceeds the currently-set range.
        return {
            i: ("OR_INPUT" if self._PEAKS.get(i, 0) > self._ranges.get(i, 1e9) else "OK")
            for i in range(1, channels + 1)
        }
