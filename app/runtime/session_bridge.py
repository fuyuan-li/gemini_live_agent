from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

from fastapi import WebSocket

from app.live.trace import build_trace_event, log_trace_event, make_session_meta, make_trace_message


class SessionBridgeError(RuntimeError):
    pass


@dataclass
class SessionBridge:
    user_id: str
    session_id: str
    websocket: WebSocket
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending_calls: Dict[str, asyncio.Future[dict]] = field(default_factory=dict)

    async def send_json(self, payload: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.websocket.send_text(json.dumps(payload))

    async def send_bytes(self, data: bytes) -> None:
        async with self.send_lock:
            await self.websocket.send_bytes(data)

    async def send_trace_event(self, payload: dict[str, Any]) -> None:
        await self.send_json(make_trace_message(payload))

    async def send_session_meta(self, *, service: str, revision: str, commit: str) -> None:
        await self.send_json(
            make_session_meta(
                session_id=self.session_id,
                service=service,
                revision=revision,
                commit=commit,
            )
        )

    async def call_tool(
        self,
        tool: str,
        args: dict[str, Any],
        timeout_s: float = 20.0,
        *,
        request_id: Optional[str] = None,
        agent_name: Optional[str] = None,
    ) -> dict[str, Any]:
        call_id = str(uuid4())
        trace_request_id = request_id or call_id
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self.pending_calls[call_id] = fut
        t0 = time.time()
        try:
            event = build_trace_event(
                request_id=trace_request_id,
                session_id=self.session_id,
                source="server",
                event="tool_called",
                status="started",
                summary=f"{tool} {args}",
                agent_name=agent_name,
                tool_name=tool,
            )
            log_trace_event(event)
            await self.send_trace_event(event)
            await self.send_json(
                {
                    "type": "tool_call",
                    "call_id": call_id,
                    "tool": tool,
                    "args": args,
                }
            )
            payload = await asyncio.wait_for(fut, timeout=timeout_s)
        except asyncio.TimeoutError as exc:
            event = build_trace_event(
                request_id=trace_request_id,
                session_id=self.session_id,
                source="server",
                event="tool_finished",
                status="error",
                summary=f"Timed out waiting for '{tool}'.",
                agent_name=agent_name,
                tool_name=tool,
                duration_ms=int((time.time() - t0) * 1000),
            )
            log_trace_event(event)
            await self.send_trace_event(event)
            raise SessionBridgeError(f"Timed out waiting for local executor to finish '{tool}'.") from exc
        finally:
            self.pending_calls.pop(call_id, None)

        if payload.get("ok"):
            result = payload.get("result")
            event = build_trace_event(
                request_id=trace_request_id,
                session_id=self.session_id,
                source="server",
                event="tool_finished",
                status="ok",
                summary=str(result),
                agent_name=agent_name,
                tool_name=tool,
                duration_ms=int((time.time() - t0) * 1000),
            )
            log_trace_event(event)
            await self.send_trace_event(event)
            if isinstance(result, dict):
                return result
            return {"ok": True, "result": result}

        err = payload.get("error")
        event = build_trace_event(
            request_id=trace_request_id,
            session_id=self.session_id,
            source="server",
            event="tool_finished",
            status="error",
            summary=str(err or f"Local executor failed for '{tool}'."),
            agent_name=agent_name,
            tool_name=tool,
            duration_ms=int((time.time() - t0) * 1000),
        )
        log_trace_event(event)
        await self.send_trace_event(event)
        raise SessionBridgeError(str(err or f"Local executor failed for '{tool}'."))

    def complete_tool_call(self, payload: dict[str, Any]) -> bool:
        call_id = payload.get("call_id")
        if not isinstance(call_id, str):
            return False

        fut = self.pending_calls.get(call_id)
        if fut is None or fut.done():
            return False

        fut.set_result(payload)
        return True

    def cancel_pending(self, reason: str) -> None:
        for fut in self.pending_calls.values():
            if not fut.done():
                fut.set_exception(SessionBridgeError(reason))
        self.pending_calls.clear()


_bridge_lock = asyncio.Lock()
_bridges: Dict[Tuple[str, str], SessionBridge] = {}


async def register_bridge(user_id: str, session_id: str, websocket: WebSocket) -> SessionBridge:
    bridge = SessionBridge(user_id=user_id, session_id=session_id, websocket=websocket)
    async with _bridge_lock:
        old_bridge = _bridges.get((user_id, session_id))
        if old_bridge is not None:
            old_bridge.cancel_pending("Bridge replaced by a newer client connection.")
        _bridges[(user_id, session_id)] = bridge
    return bridge


async def unregister_bridge(user_id: str, session_id: str, bridge: Optional[SessionBridge] = None) -> None:
    async with _bridge_lock:
        current = _bridges.get((user_id, session_id))
        if current is None:
            return
        if bridge is not None and current is not bridge:
            return
        current.cancel_pending("Client connection closed.")
        _bridges.pop((user_id, session_id), None)


async def get_bridge(user_id: str, session_id: str) -> Optional[SessionBridge]:
    async with _bridge_lock:
        return _bridges.get((user_id, session_id))


async def call_local_tool(
    user_id: str,
    session_id: str,
    tool: str,
    args: dict[str, Any],
    timeout_s: float = 20.0,
    *,
    request_id: Optional[str] = None,
    agent_name: Optional[str] = None,
) -> dict[str, Any]:
    bridge = await get_bridge(user_id, session_id)
    if bridge is None:
        raise SessionBridgeError("No local executor is connected for this session.")
    return await bridge.call_tool(
        tool=tool,
        args=args,
        timeout_s=timeout_s,
        request_id=request_id,
        agent_name=agent_name,
    )


async def handle_tool_result(user_id: str, session_id: str, payload: dict[str, Any]) -> bool:
    bridge = await get_bridge(user_id, session_id)
    if bridge is None:
        return False
    return bridge.complete_tool_call(payload)


async def send_session_meta(user_id: str, session_id: str, *, service: str, revision: str, commit: str) -> bool:
    bridge = await get_bridge(user_id, session_id)
    if bridge is None:
        return False
    await bridge.send_session_meta(service=service, revision=revision, commit=commit)
    return True


async def emit_server_trace(
    user_id: str,
    session_id: str,
    *,
    request_id: str,
    event: str,
    status: str,
    summary: str,
    agent_name: Optional[str] = None,
    tool_name: Optional[str] = None,
    duration_ms: Optional[int] = None,
    cursor: Optional[dict[str, Any]] = None,
) -> None:
    payload = build_trace_event(
        request_id=request_id,
        session_id=session_id,
        source="server",
        event=event,
        status=status,
        summary=summary,
        agent_name=agent_name,
        tool_name=tool_name,
        duration_ms=duration_ms,
        cursor=cursor,
    )
    log_trace_event(payload)
    bridge = await get_bridge(user_id, session_id)
    if bridge is not None:
        await bridge.send_trace_event(payload)
