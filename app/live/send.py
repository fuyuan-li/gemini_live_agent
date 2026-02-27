import time
from typing import Any, Awaitable, Callable

from .telemetry import OutboundTelemetry, OutboundRecord, safe_serialize, summarize


SendJson = Callable[[str, dict], Awaitable[int]]


def make_send_json(websocket: Any, telemetry: OutboundTelemetry) -> SendJson:
    """
    Wrap websocket.send to:
    - attach client_msg_id
    - serialize to UTF-8 JSON string
    - record the last outbound payload meta for debugging 1007
    """

    async def send_json(kind: str, payload: dict) -> int:
        msg_id = telemetry.next_id()

        # don't mutate caller dict unexpectedly
        payload2 = dict(payload)
        payload2["client_msg_id"] = msg_id

        json_str, size = safe_serialize(payload2)

        telemetry.set_last(
            OutboundRecord(
                msg_id=msg_id,
                ts=time.time(),
                kind=kind,
                bytes=size,
                summary=summarize(payload2),
            )
        )

        # IMPORTANT: send TEXT frame (str), not bytes
        await websocket.send(json_str)
        return msg_id

    return send_json