import json
import time
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class OutboundRecord:
    msg_id: int
    ts: float
    kind: str
    bytes: int
    summary: str


class OutboundTelemetry:
    def __init__(self) -> None:
        self._next_id = 1
        self._last: Optional[OutboundRecord] = None

    def next_id(self) -> int:
        msg_id = self._next_id
        self._next_id += 1
        return msg_id

    def set_last(self, record: OutboundRecord) -> None:
        self._last = record

    @property
    def last(self) -> Optional[OutboundRecord]:
        return self._last


def _clean_json(obj: Any) -> Any:
    # avoid NaN/Inf breaking JSON (or being rejected upstream)
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            return None
    return obj


def safe_serialize(payload: Any) -> tuple[str, int]:
    """
    Return (json_str, utf8_bytes).
    NOTE: ensure_ascii=False keeps UTF-8; websocket text frames must be UTF-8 valid.
    """
    json_str = json.dumps(payload, default=_clean_json, ensure_ascii=False)
    return json_str, len(json_str.encode("utf-8"))


def summarize(payload: Any) -> str:
    if isinstance(payload, dict):
        keys = list(payload.keys())
        return f"keys={keys[:10]}" + ("..." if len(keys) > 10 else "")
    return f"type={type(payload).__name__}"