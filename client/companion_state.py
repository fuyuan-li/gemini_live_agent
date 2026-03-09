from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Optional

from app.live.trace import build_trace_event
from client.cursor.types import CursorSample, NormalizedSample


@dataclass(frozen=True)
class CursorPoint:
    x: int
    y: int
    ts: float


@dataclass(frozen=True)
class SessionMeta:
    session_id: str
    service: str
    revision: str
    commit: str


@dataclass(frozen=True)
class EventEntry:
    event_id: str
    request_id: str
    session_id: str
    source: str
    event: str
    status: str
    summary: str
    ts: float
    agent_name: Optional[str] = None
    tool_name: Optional[str] = None
    duration_ms: Optional[int] = None
    cursor: Optional[dict[str, int]] = None
    metadata: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class CompanionSnapshot:
    connected: bool
    muted: bool
    session_meta: Optional[SessionMeta]
    current_agent: Optional[str]
    current_tool: Optional[str]
    last_summary: str
    latest_events: list[EventEntry]
    local_cursor: Optional[CursorPoint]
    server_cursor: Optional[CursorPoint]
    fingertip: Optional[NormalizedSample]
    calibration_state: str
    calibration_message: str


class CompanionState:
    def __init__(self, *, session_id: str, event_limit: int = 200) -> None:
        self.session_id = session_id
        self._lock = threading.Lock()
        self._connected = False
        self._muted = False
        self._session_meta: Optional[SessionMeta] = None
        self._current_agent: Optional[str] = None
        self._current_tool: Optional[str] = None
        self._last_summary = ""
        self._latest_events: Deque[EventEntry] = deque(maxlen=event_limit)
        self._local_cursor: Optional[CursorPoint] = None
        self._server_cursor: Optional[CursorPoint] = None
        self._fingertip: Optional[NormalizedSample] = None
        self._last_cursor_sent_trace = 0.0
        self._calibration_state = "uncalibrated"
        self._calibration_message = "Hand cursor calibration is required."
        self._local_trace_listener: Optional[Callable[[dict[str, Any]], None]] = None

    def snapshot(self) -> CompanionSnapshot:
        with self._lock:
            return CompanionSnapshot(
                connected=self._connected,
                muted=self._muted,
                session_meta=self._session_meta,
                current_agent=self._current_agent,
                current_tool=self._current_tool,
                last_summary=self._last_summary,
                latest_events=list(self._latest_events),
                local_cursor=self._local_cursor,
                server_cursor=self._server_cursor,
                fingertip=self._fingertip,
                calibration_state=self._calibration_state,
                calibration_message=self._calibration_message,
            )

    def set_connected(self, connected: bool) -> None:
        with self._lock:
            self._connected = bool(connected)

    def set_muted(self, muted: bool) -> None:
        with self._lock:
            self._muted = bool(muted)

    def toggle_muted(self) -> bool:
        with self._lock:
            self._muted = not self._muted
            return self._muted

    def get_local_cursor_xy(self) -> Optional[tuple[int, int]]:
        with self._lock:
            if self._local_cursor is None:
                return None
            return self._local_cursor.x, self._local_cursor.y

    def update_local_capture(
        self,
        *,
        cursor: Optional[CursorSample],
        fingertip: Optional[NormalizedSample],
    ) -> None:
        with self._lock:
            self._fingertip = fingertip
            if cursor is not None:
                self._local_cursor = CursorPoint(x=int(cursor.x), y=int(cursor.y), ts=float(cursor.ts))

    def set_calibration_state(self, state: str, message: str = "") -> None:
        with self._lock:
            self._calibration_state = str(state)
            self._calibration_message = str(message)

    def set_local_trace_listener(self, listener: Optional[Callable[[dict[str, Any]], None]]) -> None:
        with self._lock:
            self._local_trace_listener = listener

    def record_local_event(
        self,
        *,
        request_id: str,
        event: str,
        status: str,
        summary: str,
        agent_name: Optional[str] = None,
        tool_name: Optional[str] = None,
        duration_ms: Optional[int] = None,
        cursor: Optional[dict[str, Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        payload = build_trace_event(
            request_id=request_id,
            session_id=self.session_id,
            source="client",
            event=event,
            status=status,
            summary=summary,
            agent_name=agent_name,
            tool_name=tool_name,
            duration_ms=duration_ms,
            cursor=cursor,
            metadata=metadata,
        )
        self._apply_event(payload)
        listener: Optional[Callable[[dict[str, Any]], None]]
        with self._lock:
            listener = self._local_trace_listener
        if listener is not None:
            try:
                listener(dict(payload))
            except Exception:
                pass

    def maybe_record_cursor_sent(self, *, request_id: str, cursor: CursorPoint) -> None:
        now = time.time()
        with self._lock:
            if now - self._last_cursor_sent_trace < 1.0:
                return
            self._last_cursor_sent_trace = now
        self.record_local_event(
            request_id=request_id,
            event="cursor_sent",
            status="ok",
            summary=f"cursor=({cursor.x},{cursor.y})",
            cursor={"x": cursor.x, "y": cursor.y},
        )

    def handle_server_message(self, payload: dict[str, Any]) -> bool:
        msg_type = payload.get("type")
        if msg_type == "session_meta":
            meta = SessionMeta(
                session_id=str(payload.get("session_id", self.session_id)),
                service=str(payload.get("service", "")),
                revision=str(payload.get("revision", "")),
                commit=str(payload.get("commit", "")),
            )
            with self._lock:
                self._session_meta = meta
            return True
        if msg_type == "cursor_ack":
            cursor = payload.get("cursor") or {}
            try:
                point = CursorPoint(
                    x=int(cursor["x"]),
                    y=int(cursor["y"]),
                    ts=float(payload.get("ts", time.time())),
                )
            except Exception:
                return False
            with self._lock:
                self._server_cursor = point
            return True
        if msg_type == "trace_event":
            self._apply_event(payload)
            return True
        return False

    def _apply_event(self, payload: dict[str, Any]) -> None:
        entry = EventEntry(
            event_id=str(payload["event_id"]),
            request_id=str(payload["request_id"]),
            session_id=str(payload["session_id"]),
            source=str(payload["source"]),
            event=str(payload["event"]),
            status=str(payload["status"]),
            summary=str(payload.get("summary", "")),
            ts=float(payload["ts"]),
            agent_name=str(payload["agent_name"]) if payload.get("agent_name") else None,
            tool_name=str(payload["tool_name"]) if payload.get("tool_name") else None,
            duration_ms=int(payload["duration_ms"]) if payload.get("duration_ms") is not None else None,
            cursor=payload.get("cursor"),
            metadata=payload.get("metadata"),
        )
        if entry.event not in {"cursor_sent", "cursor_received"}:
            print(
                f"[trace][{entry.source}] event={entry.event} status={entry.status} "
                f"rid={entry.request_id} agent={entry.agent_name} tool={entry.tool_name} summary={entry.summary}"
            )
        with self._lock:
            self._latest_events.append(entry)
            if entry.agent_name:
                self._current_agent = entry.agent_name
                if entry.tool_name is None and entry.event in {
                    "agent_started",
                    "agent_finished",
                    "agent_spoke",
                    "user_spoke",
                    "session_error",
                    "session_disconnected",
                }:
                    self._current_tool = None
            if entry.tool_name:
                self._current_tool = entry.tool_name
            if entry.summary and entry.event not in {"cursor_sent", "cursor_received"}:
                self._last_summary = entry.summary
