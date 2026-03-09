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
        self.preview_window_enabled = True

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
    def __init__(self, should_start: bool = True, radius: int = 10) -> None:
        self.should_start = should_start
        self.started = False
        self.positions = []
        self.visibility = []
        self.radius = radius

    def start(self) -> bool:
        self.started = self.should_start
        return self.should_start

    def stop(self) -> None:
        self.started = False

    def update_position(self, x: int, y: int) -> None:
        self.positions.append((x, y))

    def set_visible(self, visible: bool) -> None:
        self.visibility.append(bool(visible))

    def get_last_error(self):
        return None if self.should_start else "overlay failed"

    def pump(self) -> None:
        return None


class SequencedTracker(FakeTracker):
    def __init__(self, samples: list[NormalizedSample], hold_calls: int = 24) -> None:
        super().__init__(should_start=True)
        self.samples = samples
        self.hold_calls = hold_calls
        self.call_count = 0

    def get_latest_sample(self) -> Optional[NormalizedSample]:
        idx = min(self.call_count // self.hold_calls, len(self.samples) - 1)
        self.call_count += 1
        self.latest = self.samples[idx]
        return self.latest


def test_hand_provider_maps_sample_and_updates_overlay() -> None:
    tracker = FakeTracker(should_start=True)
    tracker.latest = NormalizedSample(x=0.5, y=0.5, ts=1.0, confidence=0.9)
    overlay = FakeOverlay(should_start=True)
    mapper = CursorMapper(screen_geometry=ScreenGeometry(width=100, height=50), smoothing=1.0)

    provider = HandCursorProvider(
        tracker=tracker,
        mapper=mapper,
        overlay_ui=overlay,
        calibration_overlay_ui=FakeOverlay(radius=48),
    )

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
    provider = HandCursorProvider(
        tracker=tracker,
        overlay_ui=overlay,
        calibration_overlay_ui=FakeOverlay(radius=48),
    )

    assert provider.start() is False
    st = provider.status()
    assert st["running"] is False


def test_hand_provider_status_reports_preview_flag() -> None:
    tracker = FakeTracker(should_start=True)
    tracker.preview_window_enabled = False
    provider = HandCursorProvider(
        tracker=tracker,
        overlay_ui=FakeOverlay(),
        calibration_overlay_ui=FakeOverlay(radius=48),
    )

    assert provider.start() is True
    status = provider.status()
    provider.stop()

    assert status["preview_enabled"] is True
    assert status["preview_window_enabled"] is False


def test_hand_provider_interactive_calibration_confirms_each_corner() -> None:
    samples = [
        NormalizedSample(x=10 / 99, y=10 / 99, ts=1.0, confidence=0.9),
        NormalizedSample(x=90 / 99, y=10 / 99, ts=2.0, confidence=0.9),
        NormalizedSample(x=90 / 99, y=90 / 99, ts=3.0, confidence=0.9),
        NormalizedSample(x=10 / 99, y=90 / 99, ts=4.0, confidence=0.9),
    ]
    tracker = SequencedTracker(samples=samples, hold_calls=32)
    cursor_overlay = FakeOverlay()
    target_overlay = FakeOverlay(radius=48)
    mapper = CursorMapper(screen_geometry=ScreenGeometry(width=100, height=100), smoothing=1.0)
    provider = HandCursorProvider(
        tracker=tracker,
        mapper=mapper,
        overlay_ui=cursor_overlay,
        calibration_overlay_ui=target_overlay,
    )

    assert provider.start() is True
    ok, msg = provider.run_guided_calibration(announce=lambda _: None, dwell_s=0.2, target_timeout_s=1.2, poll_dt_s=0.01)
    provider.stop()

    assert ok is True
    assert "calibration active" in msg
    assert target_overlay.positions[:4] == [(10, 10), (90, 10), (90, 90), (10, 90)]
    assert target_overlay.visibility[:1] == [True]
    assert target_overlay.visibility[-1:] == [False]
