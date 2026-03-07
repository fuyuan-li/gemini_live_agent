import asyncio
from dataclasses import dataclass

import client.local_executor as local_executor_mod
from client.local_executor import LocalToolExecutor


@dataclass(frozen=True)
class FakeCursor:
    x: int
    y: int


class FakeProvider:
    def __init__(self, cursor: FakeCursor | None) -> None:
        self.cursor = cursor
        self.pumped = 0

    def pump_ui(self) -> None:
        self.pumped += 1

    def get_cursor(self):
        return self.cursor


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    async def send_json(self, kind: str, payload: dict) -> int:
        self.sent.append((kind, payload))
        return len(self.sent)


def test_local_executor_dispatches_navigate(monkeypatch) -> None:
    async def scenario() -> None:
        sender = FakeSender()
        provider = FakeProvider(cursor=FakeCursor(10, 20))
        executor = LocalToolExecutor(provider=provider, sender=sender)

        async def fake_navigate(url: str) -> dict:
            return {"ok": True, "url": url}

        monkeypatch.setattr(local_executor_mod, "navigate", fake_navigate)

        handled = await executor.handle_message(
            {
                "type": "tool_call",
                "call_id": "call-1",
                "tool": "navigate",
                "args": {"url": "https://example.com"},
            }
        )

        assert handled is True
        assert sender.sent == [
            (
                "tool_result",
                {
                    "type": "tool_result",
                    "call_id": "call-1",
                    "ok": True,
                    "result": {"ok": True, "url": "https://example.com"},
                },
            )
        ]

    asyncio.run(scenario())


def test_local_executor_uses_cursor_for_click_here(monkeypatch) -> None:
    async def scenario() -> None:
        sender = FakeSender()
        provider = FakeProvider(cursor=FakeCursor(111, 222))
        executor = LocalToolExecutor(provider=provider, sender=sender)

        async def fake_click_screen_point(x: int, y: int) -> dict:
            return {"ok": True, "x": x, "y": y}

        monkeypatch.setattr(local_executor_mod, "click_screen_point", fake_click_screen_point)

        handled = await executor.handle_message(
            {
                "type": "tool_call",
                "call_id": "call-2",
                "tool": "click_here",
                "args": {},
            }
        )

        assert handled is True
        assert provider.pumped == 1
        assert sender.sent[0][1]["result"] == {"ok": True, "x": 111, "y": 222}

    asyncio.run(scenario())


def test_local_executor_returns_error_for_unknown_tool() -> None:
    async def scenario() -> None:
        sender = FakeSender()
        provider = FakeProvider(cursor=FakeCursor(1, 2))
        executor = LocalToolExecutor(provider=provider, sender=sender)

        handled = await executor.handle_message(
            {
                "type": "tool_call",
                "call_id": "call-3",
                "tool": "missing_tool",
                "args": {},
            }
        )

        assert handled is True
        assert sender.sent[0][1]["ok"] is False
        assert "Unknown tool" in sender.sent[0][1]["error"]

    asyncio.run(scenario())
