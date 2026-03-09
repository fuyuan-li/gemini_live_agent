# app/runtime/genai_ws_sniffer.py
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional
import time

@dataclass
class OutboundFrame:
    ts: float
    is_bytes: bool
    nbytes: int
    head: str  # first chars for text frames (usually JSON)

_last: Optional[OutboundFrame] = None
_recent: deque[OutboundFrame] = deque(maxlen=20)


def record_outbound(message: Any, max_head_chars: int = 1200) -> None:
    global _last
    try:
        if isinstance(message, (bytes, bytearray, memoryview)):
            b = bytes(message)
            _last = OutboundFrame(ts=time.time(), is_bytes=True, nbytes=len(b), head="")
        else:
            s = str(message)
            _last = OutboundFrame(ts=time.time(), is_bytes=False, nbytes=len(s.encode("utf-8")), head=s[:max_head_chars])
        _recent.append(_last)
    except Exception:
        # never break caller
        pass


def get_last_outbound() -> Optional[OutboundFrame]:
    return _last


def get_recent_outbound() -> list[OutboundFrame]:
    return list(_recent)
