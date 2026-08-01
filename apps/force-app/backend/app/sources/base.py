"""The acquisition source contract. The sim (2a) and the future nidaqmx source (2b) both satisfy
it, so everything downstream (ring, consumers, finalize) is source-agnostic."""
from __future__ import annotations

from typing import Optional, Protocol

import numpy as np


class AcquisitionSource(Protocol):
    channels: list[str]  # signal channel names (excludes Time)
    rate: float          # samples/sec

    def start(self) -> None: ...

    def read(self) -> Optional[tuple[np.ndarray, np.ndarray]]:
        """Block until the next chunk is available; return (t[n], data[n, n_ch]) with t in
        seconds since start. Return None when the source is exhausted or stopped."""
        ...

    def stop(self) -> None: ...
