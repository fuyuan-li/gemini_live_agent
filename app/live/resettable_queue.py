from __future__ import annotations

import asyncio

from google.adk.agents.live_request_queue import LiveRequest
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.genai import types


class ResettableLiveRequestQueue(LiveRequestQueue):
    def send_content(self, content: types.Content) -> None:
        # ADK (base_llm_flow.py line 210) sends ALL function responses to the
        # queue, including transfer_to_agent. When an agent transfer happens,
        # this orphaned response ends up in the queue and gets sent to the new
        # agent's session, which can cause 1007 (model receives a function
        # response it never requested).
        if content and content.parts:
            for part in content.parts:
                fr = getattr(part, "function_response", None)
                if fr and getattr(fr, "name", None) == "transfer_to_agent":
                    return  # Drop orphaned transfer response
        super().send_content(content)

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
