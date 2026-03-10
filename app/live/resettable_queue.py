from __future__ import annotations

import asyncio

from google.adk.agents.live_request_queue import LiveRequest
from google.adk.agents.live_request_queue import LiveRequestQueue


class ResettableLiveRequestQueue(LiveRequestQueue):
    def drop_realtime_backlog(self) -> int:
        dropped = 0
        kept: list[LiveRequest] = []

        while True:
            try:
                req = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            if req.close or req.content is not None:
                kept.append(req)
                continue
            if req.activity_start or req.activity_end or req.blob is not None:
                dropped += 1
                continue
            kept.append(req)

        for req in kept:
            self._queue.put_nowait(req)
        return dropped
