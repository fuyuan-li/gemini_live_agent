# client/ws_guard.py
import json
import time
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class OutboundRecord:
    msg_id: int
    ts: float
    kind: str
    is_binary: bool
    bytes: int
    summary: str


class OutboundTelemetry:
    def __init__(self) -> None:
        self._next_id = 1
        self._last: Optional[OutboundRecord] = None

    def next_id(self) -> int:
        mid = self._next_id
        self._next_id += 1
        return mid

    def set_last(self, rec: OutboundRecord) -> None:
        self._last = rec

    @property
    def last(self) -> Optional[OutboundRecord]:
        return self._last


def _safe_json_dumps(payload: Any) -> str:
    # guard against NaN/Inf & non-serializable objects
    def default(o):
        if isinstance(o, float) and (o != o or o in (float("inf"), float("-inf"))):
            return None
        return str(o)

    return json.dumps(payload, ensure_ascii=False, default=default)


def _summarize(payload: Any) -> str:
    if isinstance(payload, dict):
        keys = list(payload.keys())
        return f"keys={keys[:10]}" + ("..." if len(keys) > 10 else "")
    return f"type={type(payload).__name__}"


class WSSender:
    """
    Wrap ws.send so we can log last outbound message (to debug 1007)
    """
    def __init__(self, ws: Any, telemetry: OutboundTelemetry) -> None:
        self.ws = ws
        self.tel = telemetry

    async def send_json(self, kind: str, payload: dict) -> int:
        msg_id = self.tel.next_id()
        payload2 = dict(payload)
        payload2["client_msg_id"] = msg_id

        s = _safe_json_dumps(payload2)
        b = len(s.encode("utf-8"))

        self.tel.set_last(
            OutboundRecord(
                msg_id=msg_id,
                ts=time.time(),
                kind=kind,
                is_binary=False,
                bytes=b,
                summary=_summarize(payload2),
            )
        )

        # IMPORTANT: send TEXT frame as str (UTF-8)
        await self.ws.send(s)
        return msg_id

    async def send_bytes(self, kind: str, data: bytes) -> int:
        msg_id = self.tel.next_id()
        n = len(data)

        self.tel.set_last(
            OutboundRecord(
                msg_id=msg_id,
                ts=time.time(),
                kind=kind,
                is_binary=True,
                bytes=n,
                summary=f"bytes_len={n}",
            )
        )

        await self.ws.send(data)
        return msg_id