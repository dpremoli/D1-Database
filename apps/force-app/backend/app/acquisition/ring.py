"""Bounded producer/consumer handoff between the acquisition source and the consumer thread.

A 2a `Ring` is a bounded `queue.Queue` of chunk tuples. The producer (source thread) copies each
chunk in and returns; a single consumer thread drains it, writing raw-to-disk (never dropped) and
producing display frames. The bound provides backpressure: for the rate-limited sim the queue stays
near-empty; with a real DAQ a persistent backlog signals a consumer overrun (surfaced by the
caller). Kept deliberately simple — a pre-allocated ndarray ring is a 2b optimisation if needed.
"""

from __future__ import annotations

import queue

import numpy as np

_SENTINEL = object()


class Ring:
    def __init__(self, maxsize: int = 64):
        self._q: queue.Queue = queue.Queue(maxsize=maxsize)

    def put(self, t: np.ndarray, data: np.ndarray, timeout: float | None = None) -> bool:
        """Enqueue a chunk. Returns False if it timed out (consumer overrun)."""
        try:
            self._q.put((t, data), timeout=timeout)
            return True
        except queue.Full:
            return False

    def get(self, timeout: float | None = None) -> tuple[np.ndarray, np.ndarray] | None:
        """Dequeue a chunk, or None when the stream has been closed."""
        item = self._q.get(timeout=timeout)
        if item is _SENTINEL:
            return None
        return item

    def close(self) -> None:
        """Signal end-of-stream to the consumer."""
        self._q.put(_SENTINEL)

    def qsize(self) -> int:
        return self._q.qsize()
