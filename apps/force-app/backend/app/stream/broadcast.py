"""Thread→asyncio bridge for fanning live frames out to connected WebSocket clients.

The acquisition consumer runs in a worker thread; WebSocket sends must happen on the event loop.
`publish` is thread-safe (schedules the fan-out via `call_soon_threadsafe`); each subscriber has a
small bounded queue and we drop the oldest frame under backpressure (display frames are best-effort).
"""
from __future__ import annotations

import asyncio
from typing import Union


class Broadcaster:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._subs: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=8)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, message: Union[bytes, str]) -> None:
        """Call from any thread."""
        self._loop.call_soon_threadsafe(self._fanout, message)

    def _fanout(self, message: Union[bytes, str]) -> None:
        for q in self._subs:
            if q.full():
                try:
                    q.get_nowait()  # drop oldest
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                pass
