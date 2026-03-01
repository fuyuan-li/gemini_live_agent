from __future__ import annotations

import queue

from client.cursor_debug import run_cursor_debug
from client.cursor.types import CursorSample


class FakeProvider:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.overlay_toggled = 0

    def start(self) -> bool:
        self.started = True
        return True

    def stop(self) -> None:
        self.stopped = True

    def get_cursor(self):
        return CursorSample(x=10, y=20, ts=1.0, source="hand", confidence=1.0)

    def status(self):
        return {"running": True, "preview_enabled": True}

    def toggle_overlay(self):
        self.overlay_toggled += 1
        return True

    def set_overlay_visible(self, visible: bool):
        return bool(visible)

    def run_guided_calibration(self, announce=None):
        return True, "ok"

    def clear_calibration(self):
        return True, "cleared"

    def pump_ui(self) -> None:
        return None


def test_cursor_debug_handles_overlay_and_quit_commands() -> None:
    provider = FakeProvider()
    cmd_q: "queue.Queue[str]" = queue.Queue()
    cmd_q.put("toggle_overlay")
    cmd_q.put("quit")

    run_cursor_debug(
        provider,
        poll_hz=200.0,
        print_hz=200.0,
        duration_seconds=5.0,
        command_queue=cmd_q,
    )

    assert provider.started is True
    assert provider.stopped is True
    assert provider.overlay_toggled == 1
