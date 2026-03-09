import asyncio
from dataclasses import dataclass

import client.local_executor as local_executor_mod
from client.local_executor import LocalToolExecutor


@dataclass(frozen=True)
class FakeCursor:
    x: int
    y: int


@dataclass(frozen=True)
class FakeWindowBounds:
    left: int
    top: int
    width: int
    height: int


@dataclass(frozen=True)
class FakeGeometry:
    display_id: int | None
    viewport_origin: tuple[int, int]
    viewport_size: tuple[int, int]
    window_bounds: FakeWindowBounds


class FakeProvider:
    def __init__(
        self,
        cursor: FakeCursor | None,
        *,
        source: str = "mouse",
        calibrated: bool = True,
        calibration_display_id: int | None = None,
    ) -> None:
        self.cursor = cursor
        self.pumped = 0
        self.source = source
        self.calibrated = calibrated
        self.calibration_display_id = calibration_display_id

    def pump_ui(self) -> None:
        self.pumped += 1

    def get_cursor(self):
        return self.cursor

    def status(self):
        return {
            "source": self.source,
            "calibrated": self.calibrated,
            "calibration_display_id": self.calibration_display_id,
        }


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
        provider = FakeProvider(
            cursor=FakeCursor(111, 222),
            source="hand",
            calibrated=True,
            calibration_display_id=1,
        )
        executor = LocalToolExecutor(provider=provider, sender=sender)

        async def fake_click_screen_point(x: int, y: int, *, geometry=None) -> dict:
            return {"ok": True, "x": x, "y": y}

        async def fake_refresh_browser_geometry():
            return FakeGeometry(
                display_id=1,
                viewport_origin=(10, 20),
                viewport_size=(1280, 800),
                window_bounds=FakeWindowBounds(left=0, top=0, width=1400, height=900),
            )

        monkeypatch.setattr(local_executor_mod, "click_screen_point", fake_click_screen_point)
        monkeypatch.setattr(local_executor_mod, "refresh_browser_geometry", fake_refresh_browser_geometry)

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


def test_local_executor_blocks_here_when_uncalibrated(monkeypatch) -> None:
    async def scenario() -> None:
        sender = FakeSender()
        provider = FakeProvider(cursor=FakeCursor(111, 222), source="hand", calibrated=False)
        executor = LocalToolExecutor(provider=provider, sender=sender)

        handled = await executor.handle_message(
            {
                "type": "tool_call",
                "call_id": "call-uncal",
                "tool": "click_here",
                "args": {},
            }
        )

        assert handled is True
        assert sender.sent[0][1]["ok"] is False
        assert "calibration" in sender.sent[0][1]["error"].lower()

    asyncio.run(scenario())


def test_local_executor_blocks_here_when_browser_is_on_other_display(monkeypatch) -> None:
    async def scenario() -> None:
        sender = FakeSender()
        provider = FakeProvider(
            cursor=FakeCursor(111, 222),
            source="hand",
            calibrated=True,
            calibration_display_id=1,
        )
        executor = LocalToolExecutor(provider=provider, sender=sender)

        async def fake_refresh_browser_geometry():
            return FakeGeometry(
                display_id=2,
                viewport_origin=(10, 20),
                viewport_size=(1280, 800),
                window_bounds=FakeWindowBounds(left=1500, top=0, width=1400, height=900),
            )

        monkeypatch.setattr(local_executor_mod, "refresh_browser_geometry", fake_refresh_browser_geometry)

        handled = await executor.handle_message(
            {
                "type": "tool_call",
                "call_id": "call-display",
                "tool": "click_here",
                "args": {},
            }
        )

        assert handled is True
        assert sender.sent[0][1]["ok"] is False
        assert "cross-screen" in sender.sent[0][1]["error"]

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


def test_local_executor_prefers_cursor_supplier_over_provider(monkeypatch) -> None:
    async def scenario() -> None:
        sender = FakeSender()
        provider = FakeProvider(
            cursor=FakeCursor(111, 222),
            source="hand",
            calibrated=True,
            calibration_display_id=1,
        )
        supplier_calls: list[int] = []

        def cursor_supplier() -> tuple[int, int]:
            supplier_calls.append(1)
            return (333, 444)

        executor = LocalToolExecutor(
            provider=provider,
            sender=sender,
            cursor_supplier=cursor_supplier,
        )

        async def fake_click_screen_point(x: int, y: int, *, geometry=None) -> dict:
            return {"ok": True, "x": x, "y": y}

        async def fake_refresh_browser_geometry():
            return FakeGeometry(
                display_id=1,
                viewport_origin=(10, 20),
                viewport_size=(1280, 800),
                window_bounds=FakeWindowBounds(left=0, top=0, width=1400, height=900),
            )

        monkeypatch.setattr(local_executor_mod, "click_screen_point", fake_click_screen_point)
        monkeypatch.setattr(local_executor_mod, "refresh_browser_geometry", fake_refresh_browser_geometry)

        handled = await executor.handle_message(
            {
                "type": "tool_call",
                "call_id": "call-supplier",
                "tool": "click_here",
                "args": {},
            }
        )

        assert handled is True
        assert supplier_calls == [1]
        assert provider.pumped == 0
        assert sender.sent[0][1]["result"] == {"ok": True, "x": 333, "y": 444}

    asyncio.run(scenario())
