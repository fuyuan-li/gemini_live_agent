import asyncio
import json

import pytest

from app.runtime.session_bridge import (
    SessionBridgeError,
    call_local_tool,
    handle_tool_result,
    register_bridge,
    unregister_bridge,
)


class FakeWebSocket:
    def __init__(self) -> None:
        self.text_frames: list[dict] = []
        self.binary_frames: list[bytes] = []

    async def send_text(self, payload: str) -> None:
        self.text_frames.append(json.loads(payload))

    async def send_bytes(self, payload: bytes) -> None:
        self.binary_frames.append(payload)


def test_call_local_tool_round_trip() -> None:
    async def scenario() -> None:
        ws = FakeWebSocket()
        bridge = await register_bridge("user", "session", ws)
        try:
            task = asyncio.create_task(
                call_local_tool(
                    user_id="user",
                    session_id="session",
                    tool="navigate",
                    args={"url": "https://example.com"},
                    timeout_s=0.5,
                )
            )
            await asyncio.sleep(0)

            assert len(ws.text_frames) == 1
            sent = ws.text_frames[0]
            assert sent["type"] == "tool_call"
            assert sent["tool"] == "navigate"
            assert sent["args"] == {"url": "https://example.com"}

            handled = await handle_tool_result(
                "user",
                "session",
                {
                    "type": "tool_result",
                    "call_id": sent["call_id"],
                    "ok": True,
                    "result": {"ok": True, "url": "https://example.com"},
                },
            )
            assert handled is True

            result = await task
            assert result == {"ok": True, "url": "https://example.com"}
        finally:
            await unregister_bridge("user", "session", bridge)

    asyncio.run(scenario())


def test_call_local_tool_without_bridge_errors() -> None:
    async def scenario() -> None:
        with pytest.raises(SessionBridgeError):
            await call_local_tool("missing", "missing", "navigate", {"url": "https://example.com"}, timeout_s=0.1)

    asyncio.run(scenario())
