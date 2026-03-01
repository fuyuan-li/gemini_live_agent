from __future__ import annotations

import statistics
import time
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

from .mapper import CursorMapper
from .types import CursorSample
from .ui_overlay import ScreenDotOverlay
from .webcam_tracker import WebcamFingerTracker


class CursorProvider(Protocol):
    def start(self) -> bool:
        ...

    def stop(self) -> None:
        ...

    def get_cursor(self) -> Optional[CursorSample]:
        ...

    def pump_ui(self) -> None:
        ...

    def status(self) -> Dict[str, Any]:
        ...


class MouseCursorProvider:
    def __init__(self) -> None:
        try:
            from pynput.mouse import Controller
        except Exception as exc:
            raise RuntimeError(f"pynput is required for MouseCursorProvider: {exc}")

        self._mouse = Controller()

    def start(self) -> bool:
        return True

    def stop(self) -> None:
        return None

    def get_cursor(self) -> Optional[CursorSample]:
        x, y = self._mouse.position
        return CursorSample(x=int(x), y=int(y), ts=time.time(), source="mouse", confidence=1.0)

    def pump_ui(self) -> None:
        return None

    def status(self) -> Dict[str, Any]:
        return {
            "source": "mouse",
            "running": True,
            "last_error": None,
        }


class HandCursorProvider:
    def __init__(
        self,
        *,
        camera_index: int = 0,
        smoothing: float = 0.35,
        stale_timeout_s: float = 0.4,
        tracker_start_timeout_s: float = 8.0,
        mirror: bool = True,
        preview: bool = True,
        overlay: bool = True,
        overlay_radius: int = 10,
        tracker: Optional[WebcamFingerTracker] = None,
        mapper: Optional[CursorMapper] = None,
        overlay_ui: Optional[ScreenDotOverlay] = None,
    ) -> None:
        self.tracker = tracker or WebcamFingerTracker(
            camera_index=camera_index,
            mirror=mirror,
            preview_enabled=preview,
        )
        self.mapper = mapper or CursorMapper(
            smoothing=smoothing,
            stale_timeout_s=stale_timeout_s,
        )

        self.overlay = overlay_ui
        if self.overlay is None and overlay:
            self.overlay = ScreenDotOverlay(radius=overlay_radius, visible=True)

        self.tracker_start_timeout_s = float(max(0.5, tracker_start_timeout_s))
        self._running = False
        self._last_error: Optional[str] = None

    def start(self) -> bool:
        if self.overlay is not None:
            ok = self.overlay.start()
            if not ok:
                self._last_error = self.overlay.get_last_error() or "overlay failed to start"
                return False

        ok = self.tracker.start(timeout_s=self.tracker_start_timeout_s)
        if not ok:
            tracker_err = self.tracker.get_last_error()
            health = self.tracker.get_health()
            self._last_error = (
                tracker_err
                or f"tracker failed to start (running={health.running}, frames_seen={health.frames_seen})"
            )
            if self.overlay is not None:
                self.overlay.stop()
            self._running = False
            return False

        self._running = True
        self._last_error = None
        return True

    def stop(self) -> None:
        self.tracker.stop()
        if self.overlay is not None:
            self.overlay.stop()
        self._running = False

    def get_cursor(self) -> Optional[CursorSample]:
        sample = self.tracker.get_latest_sample()
        if sample is not None:
            cur = self.mapper.update_from_normalized(
                sample.x,
                sample.y,
                ts=sample.ts,
                source="hand",
                confidence=sample.confidence,
            )
        else:
            cur = self.mapper.get_fallback()

        if self.overlay is not None:
            if cur is not None:
                self.overlay.update_position(cur.x, cur.y)
            else:
                self.overlay.pump()
        return cur

    def pump_ui(self) -> None:
        self.tracker.pump_preview()
        if self.overlay is not None:
            self.overlay.pump()

    def set_overlay_visible(self, visible: bool) -> Optional[bool]:
        if self.overlay is None:
            return None
        self.overlay.set_visible(bool(visible))
        return bool(visible)

    def toggle_overlay(self) -> Optional[bool]:
        if self.overlay is None:
            return None
        return self.overlay.toggle_visible()

    def clear_calibration(self) -> Tuple[bool, str]:
        self.mapper.clear_calibration()
        return True, "calibration cleared"

    def run_guided_calibration(
        self,
        *,
        announce: Optional[Callable[[str], None]] = None,
        settle_s: float = 1.2,
        sample_s: float = 1.2,
        sample_hz: float = 30.0,
    ) -> Tuple[bool, str]:
        """
        4-point guided calibration. We place target dots on screen corners and
        collect median normalized fingertip coordinates for each target.
        """

        say = announce or print
        targets = self.mapper.get_calibration_targets()

        camera_points: List[Tuple[float, float]] = []
        screen_points: List[Tuple[int, int]] = []

        say("[calibration] Starting 4-point calibration...")
        say("[calibration] Keep one hand visible and point index fingertip to each target.")

        for idx, (name, sx, sy) in enumerate(targets, start=1):
            if self.overlay is not None:
                self.overlay.set_visible(True)
                self.overlay.update_position(sx, sy)

            say(f"[calibration] {idx}/4 target={name} at ({sx},{sy}). Hold steady...")

            t_settle_end = time.time() + max(0.1, settle_s)
            while time.time() < t_settle_end:
                self.pump_ui()
                time.sleep(0.01)

            samples: List[Tuple[float, float]] = []
            t_sample_end = time.time() + max(0.3, sample_s)
            dt = 1.0 / max(5.0, sample_hz)
            while time.time() < t_sample_end:
                self.pump_ui()
                s = self.tracker.get_latest_sample()
                if s is not None:
                    samples.append((float(s.x), float(s.y)))
                time.sleep(dt)

            if len(samples) < 8:
                return False, (
                    f"calibration failed at {name}: not enough hand samples "
                    f"({len(samples)}). Keep hand visible and retry."
                )

            x_med = statistics.median(p[0] for p in samples)
            y_med = statistics.median(p[1] for p in samples)

            camera_points.append((x_med, y_med))
            screen_points.append((sx, sy))
            say(f"[calibration] captured {name}: cam=({x_med:.3f},{y_med:.3f}) -> screen=({sx},{sy})")

        ok, msg = self.mapper.calibrate_from_correspondences(camera_points, screen_points)
        if not ok:
            return False, msg

        say("[calibration] Completed. Calibration is active for this process.")
        return True, msg

    def status(self) -> Dict[str, Any]:
        health = self.tracker.get_health()
        return {
            "source": "hand",
            "running": self._running and health.running,
            "last_error": self._last_error or health.last_error,
            "last_seen_ts": health.last_seen_ts,
            "frames_seen": health.frames_seen,
            "preview_enabled": bool(self.tracker.preview_enabled),
            "overlay_enabled": self.overlay is not None,
            "calibrated": self.mapper.has_calibration(),
        }
