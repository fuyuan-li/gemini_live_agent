from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

from fastapi import WebSocket


class SessionBridgeError(RuntimeError):
    pass


@dataclass
class SessionBridge:
    websocket: WebSocket
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending_calls: Dict[str, asyncio.Future[dict]] = field(default_factory=dict)

    async def send_json(self, payload: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.websocket.send_text(json.dumps(payload))

    async def send_bytes(self, data: bytes) -> None:
        async with self.send_lock:
            await self.websocket.send_bytes(data)

    async def call_tool(self, tool: str, args: dict[str, Any], timeout_s: float = 20.0) -> dict[str, Any]:
        call_id = str(uuid4())
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self.pending_calls[call_id] = fut
        try:
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
            raise SessionBridgeError(f"Timed out waiting for local executor to finish '{tool}'.") from exc
        finally:
            self.pending_calls.pop(call_id, None)

        if payload.get("ok"):
            result = payload.get("result")
            if isinstance(result, dict):
                return result
            return {"ok": True, "result": result}

        err = payload.get("error")
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
    bridge = SessionBridge(websocket=websocket)
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
) -> dict[str, Any]:
    bridge = await get_bridge(user_id, session_id)
    if bridge is None:
        raise SessionBridgeError("No local executor is connected for this session.")
    return await bridge.call_tool(tool=tool, args=args, timeout_s=timeout_s)


async def handle_tool_result(user_id: str, session_id: str, payload: dict[str, Any]) -> bool:
    bridge = await get_bridge(user_id, session_id)
    if bridge is None:
        return False
    return bridge.complete_tool_call(payload)
