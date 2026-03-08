from __future__ import annotations

from collections import deque
from typing import Any, Callable, Deque, Dict, Optional, Set

from app.tools.browser.mouse import (
    click_screen_point,
    drag_screen_point_by_offset,
    pan,
    scroll_screen_point,
)
from app.tools.browser.navigation import navigate
from client.cursor.provider import CursorProvider
from client.ws_guard import WSSender


class LocalToolExecutor:
    def __init__(
        self,
        provider: Optional[CursorProvider],
        sender: WSSender,
        *,
        cursor_supplier: Optional[Callable[[], Optional[tuple[int, int]]]] = None,
        event_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        self.provider = provider
        self.sender = sender
        self.cursor_supplier = cursor_supplier
        self.event_callback = event_callback
        self._recent_ids: Deque[str] = deque(maxlen=256)
        self._recent_id_set: Set[str] = set()

    async def handle_message(self, payload: dict[str, Any]) -> bool:
        if payload.get("type") != "tool_call":
            return False

        call_id = payload.get("call_id")
        tool = payload.get("tool")
        args = payload.get("args", {})

        if not isinstance(call_id, str) or not call_id:
            return True
        if not isinstance(tool, str) or not tool:
            await self._send_error(call_id, "Missing tool name.")
            return True
        if not isinstance(args, dict):
            await self._send_error(call_id, "Tool arguments must be a JSON object.")
            return True

        if call_id in self._recent_id_set:
            return True

        try:
            self._emit(
                {
                    "event": "tool_result_received",
                    "status": "started",
                    "summary": f"local executor handling {tool}",
                    "tool_name": tool,
                    "request_id": call_id,
                }
            )
            result = await self._dispatch(tool, args)
        except Exception as exc:
            await self._send_error(call_id, str(exc))
            self._emit(
                {
                    "event": "tool_result_received",
                    "status": "error",
                    "summary": str(exc),
                    "tool_name": tool,
                    "request_id": call_id,
                }
            )
        else:
            await self.sender.send_json(
                "tool_result",
                {
                    "type": "tool_result",
                    "call_id": call_id,
                    "ok": True,
                    "result": result,
                },
            )
            self._emit(
                {
                    "event": "tool_result_received",
                    "status": "ok",
                    "summary": str(result),
                    "tool_name": tool,
                    "request_id": call_id,
                }
            )

        self._remember_call_id(call_id)
        return True

    async def _dispatch(self, tool: str, args: Dict[str, Any]) -> dict:
        if tool == "navigate":
            url = args.get("url")
            if not isinstance(url, str) or not url.strip():
                raise RuntimeError("navigate requires a non-empty url.")
            return await navigate(url=url)

        if tool == "pan":
            direction = args.get("direction")
            if not isinstance(direction, str) or not direction.strip():
                raise RuntimeError("pan requires a direction.")
            amount = int(args.get("amount", 300))
            return await pan(direction=direction, amount=amount)

        if tool == "click_here":
            x, y = self._get_cursor_xy()
            return await click_screen_point(x=x, y=y)

        if tool == "scroll_here":
            x, y = self._get_cursor_xy()
            return await scroll_screen_point(
                x=x,
                y=y,
                delta_y=int(args.get("delta_y", 0)),
                delta_x=int(args.get("delta_x", 0)),
            )

        if tool == "drag_here":
            x, y = self._get_cursor_xy()
            return await drag_screen_point_by_offset(
                x=x,
                y=y,
                dx=int(args.get("dx", 0)),
                dy=int(args.get("dy", 0)),
                steps=int(args.get("steps", 30)),
            )

        raise RuntimeError(f"Unknown tool: {tool}")

    def _get_cursor_xy(self) -> tuple[int, int]:
        if self.cursor_supplier is not None:
            cur = self.cursor_supplier()
            if cur is None:
                raise RuntimeError("No local cursor position is available yet.")
            return int(cur[0]), int(cur[1])

        if self.provider is None:
            raise RuntimeError("No cursor provider is configured.")
        self.provider.pump_ui()
        cur = self.provider.get_cursor()
        if cur is None:
            raise RuntimeError("No local cursor position is available yet.")
        return int(cur.x), int(cur.y)

    async def _send_error(self, call_id: str, message: str) -> None:
        await self.sender.send_json(
            "tool_result",
            {
                "type": "tool_result",
                "call_id": call_id,
                "ok": False,
                "error": message,
            },
        )

    def _remember_call_id(self, call_id: str) -> None:
        if call_id in self._recent_id_set:
            return

        if len(self._recent_ids) == self._recent_ids.maxlen:
            old_id = self._recent_ids.popleft()
            self._recent_id_set.discard(old_id)

        self._recent_ids.append(call_id)
        self._recent_id_set.add(call_id)

    def _emit(self, payload: dict[str, Any]) -> None:
        if self.event_callback is None:
            return
        self.event_callback(payload)
