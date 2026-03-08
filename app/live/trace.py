from __future__ import annotations

import json
import logging
import time
from typing import Any, Mapping, Optional
from uuid import uuid4


logger = logging.getLogger("companion.trace")


def new_event_id() -> str:
    return str(uuid4())


def summarize_payload(payload: Any, *, limit: int = 160) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        text = payload.strip()
    elif isinstance(payload, Mapping):
        keys = list(payload.keys())
        text = f"keys={keys[:8]}"
    else:
        text = str(payload)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def build_trace_event(
    *,
    request_id: str,
    session_id: str,
    source: str,
    event: str,
    status: str,
    summary: str = "",
    agent_name: Optional[str] = None,
    tool_name: Optional[str] = None,
    duration_ms: Optional[int] = None,
    cursor: Optional[Mapping[str, Any]] = None,
    ts: Optional[float] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event_id": event_id or new_event_id(),
        "request_id": str(request_id),
        "session_id": str(session_id),
        "source": str(source),
        "event": str(event),
        "status": str(status),
        "summary": summarize_payload(summary),
        "ts": float(time.time() if ts is None else ts),
    }
    if agent_name:
        payload["agent_name"] = str(agent_name)
    if tool_name:
        payload["tool_name"] = str(tool_name)
    if duration_ms is not None:
        payload["duration_ms"] = int(duration_ms)
    if cursor is not None:
        payload["cursor"] = {
            "x": int(cursor["x"]),
            "y": int(cursor["y"]),
        }
    return payload


def make_trace_message(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "trace_event",
        **dict(event),
    }


def make_session_meta(
    *,
    session_id: str,
    service: str,
    revision: str,
    commit: str,
) -> dict[str, Any]:
    return {
        "type": "session_meta",
        "session_id": str(session_id),
        "service": str(service),
        "revision": str(revision),
        "commit": str(commit),
    }


def make_cursor_ack(
    *,
    session_id: str,
    request_id: str,
    x: int,
    y: int,
    ts: Optional[float] = None,
) -> dict[str, Any]:
    return {
        "type": "cursor_ack",
        "session_id": str(session_id),
        "request_id": str(request_id),
        "cursor": {
            "x": int(x),
            "y": int(y),
        },
        "ts": float(time.time() if ts is None else ts),
    }


def log_trace_event(event: Mapping[str, Any]) -> None:
    logger.info(json.dumps({"trace_event": dict(event)}, ensure_ascii=False, sort_keys=True))
