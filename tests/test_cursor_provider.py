from __future__ import annotations

from typing import Optional

from client.cursor.mapper import CursorMapper, ScreenGeometry
from client.cursor.provider import HandCursorProvider
from client.cursor.types import NormalizedSample, TrackerHealth


class FakeTracker:
    def __init__(self, should_start: bool = True) -> None:
        self.should_start = should_start
        self.running = False
        self.latest: Optional[NormalizedSample] = None
        self.preview_enabled = True

    def start(self, timeout_s: float = 3.0) -> bool:
        self.running = self.should_start
        return self.should_start

    def stop(self) -> None:
        self.running = False

    def get_last_error(self):
        return None if self.should_start else "tracker failed"

    def get_latest_sample(self) -> Optional[NormalizedSample]:
        return self.latest

    def get_health(self) -> TrackerHealth:
        return TrackerHealth(
            running=self.running,
            last_error=None,
            last_seen_ts=self.latest.ts if self.latest else None,
            frames_seen=1 if self.latest else 0,
        )

    def pump_preview(self) -> None:
        return None


class FakeOverlay:
    def __init__(self, should_start: bool = True) -> None:
        self.should_start = should_start
        self.started = False
        self.positions = []

    def start(self) -> bool:
        self.started = self.should_start
        return self.should_start

    def stop(self) -> None:
        self.started = False

    def update_position(self, x: int, y: int) -> None:
        self.positions.append((x, y))

    def get_last_error(self):
        return None if self.should_start else "overlay failed"

    def pump(self) -> None:
        return None


def test_hand_provider_maps_sample_and_updates_overlay() -> None:
    tracker = FakeTracker(should_start=True)
    tracker.latest = NormalizedSample(x=0.5, y=0.5, ts=1.0, confidence=0.9)
    overlay = FakeOverlay(should_start=True)
    mapper = CursorMapper(screen_geometry=ScreenGeometry(width=100, height=50), smoothing=1.0)

    provider = HandCursorProvider(tracker=tracker, mapper=mapper, overlay_ui=overlay)

    assert provider.start() is True
    cur = provider.get_cursor()
    provider.stop()

    assert cur is not None
    assert cur.x == 50
    assert cur.y == 24
    assert overlay.positions[-1] == (50, 24)


def test_hand_provider_start_fails_when_tracker_fails() -> None:
    tracker = FakeTracker(should_start=False)
    overlay = FakeOverlay(should_start=True)
    provider = HandCursorProvider(tracker=tracker, overlay_ui=overlay)

    assert provider.start() is False
    st = provider.status()
    assert st["running"] is False


def test_hand_provider_status_reports_preview_flag() -> None:
    tracker = FakeTracker(should_start=True)
    provider = HandCursorProvider(tracker=tracker, overlay_ui=FakeOverlay())

    assert provider.start() is True
    status = provider.status()
    provider.stop()

    assert status["preview_enabled"] is True
