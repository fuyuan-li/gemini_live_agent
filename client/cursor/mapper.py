from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import cv2  # type: ignore
import numpy as np  # type: ignore

from .displays import get_main_display_geometry
from .types import CursorSample


@dataclass(frozen=True)
class ScreenGeometry:
    width: int
    height: int
    display_id: Optional[int] = None


def get_main_display_size() -> Tuple[int, int]:
    """
    Return main display size on macOS via Quartz, fallback to 1920x1080.
    """
    geom = get_main_display_geometry()
    return geom.width, geom.height


class CursorMapper:
    def __init__(
        self,
        screen_geometry: Optional[ScreenGeometry] = None,
        smoothing: float = 0.35,
        stale_timeout_s: float = 0.4,
    ) -> None:
        if screen_geometry is None:
            geom = get_main_display_geometry()
            screen_geometry = ScreenGeometry(width=geom.width, height=geom.height, display_id=geom.display_id)

        self.screen_geometry = screen_geometry
        self.smoothing = float(min(1.0, max(0.0, smoothing)))
        self.stale_timeout_s = float(max(0.0, stale_timeout_s))

        self._smoothed_xy: Optional[Tuple[float, float]] = None
        self._last_cursor: Optional[CursorSample] = None

        # 3x3 homography matrix mapping normalized camera coords -> screen px.
        self._homography = None
        self._calibration_display_id: Optional[int] = None

    def reset(self) -> None:
        self._smoothed_xy = None
        self._last_cursor = None

    def has_calibration(self) -> bool:
        return self._homography is not None

    def get_calibration_display_id(self) -> Optional[int]:
        return self._calibration_display_id

    def get_calibration_targets(self, margin_ratio: float = 0.10) -> List[Tuple[str, int, int]]:
        mx = int(self.screen_geometry.width * margin_ratio)
        my = int(self.screen_geometry.height * margin_ratio)
        w = self.screen_geometry.width
        h = self.screen_geometry.height
        return [
            ("top_left", mx, my),
            ("top_right", w - mx, my),
            ("bottom_right", w - mx, h - my),
            ("bottom_left", mx, h - my),
        ]

    def clear_calibration(self) -> None:
        self._homography = None
        self._calibration_display_id = None
        self.reset()

    def update_from_normalized(
        self,
        x_norm: float,
        y_norm: float,
        *,
        ts: Optional[float] = None,
        source: str = "hand",
        confidence: Optional[float] = None,
    ) -> CursorSample:
        now = float(time.time() if ts is None else ts)

        x_n = min(1.0, max(0.0, float(x_norm)))
        y_n = min(1.0, max(0.0, float(y_norm)))

        raw_x, raw_y = self._map_to_screen(x_n, y_n)

        if self._smoothed_xy is None:
            smoothed_x, smoothed_y = raw_x, raw_y
        else:
            alpha = self.smoothing
            smoothed_x = alpha * raw_x + (1.0 - alpha) * self._smoothed_xy[0]
            smoothed_y = alpha * raw_y + (1.0 - alpha) * self._smoothed_xy[1]

        self._smoothed_xy = (smoothed_x, smoothed_y)

        x = int(min(max(round(smoothed_x), 0), self.screen_geometry.width - 1))
        y = int(min(max(round(smoothed_y), 0), self.screen_geometry.height - 1))

        self._last_cursor = CursorSample(
            x=x,
            y=y,
            ts=now,
            source="mouse" if source == "mouse" else "hand",
            confidence=confidence,
        )
        return self._last_cursor

    def get_fallback(self, *, now_ts: Optional[float] = None) -> Optional[CursorSample]:
        if self._last_cursor is None:
            return None

        now = float(time.time() if now_ts is None else now_ts)
        if now - self._last_cursor.ts <= self.stale_timeout_s:
            return self._last_cursor
        return None

    def calibrate_from_correspondences(
        self,
        camera_points_norm: Sequence[Tuple[float, float]],
        screen_points_px: Sequence[Tuple[int, int]],
    ) -> Tuple[bool, str]:
        if len(camera_points_norm) < 4 or len(screen_points_px) < 4:
            return False, "need at least 4 correspondence points"

        # TODO: If we later persist calibration across runs, store it in Firestore
        # keyed by (user_id, device_id). Do not write package-local JSON, and do
        # not reuse the server's realtime session cursor cache for calibration.
        try:
            src = np.array(camera_points_norm[:4], dtype=np.float32)
            dst = np.array(screen_points_px[:4], dtype=np.float32)
            H = cv2.getPerspectiveTransform(src, dst)
        except Exception as exc:
            return False, f"failed to estimate calibration transform: {exc}"

        self._homography = H
        self._calibration_display_id = self.screen_geometry.display_id
        self.reset()
        return True, "calibration active for current process"

    def _map_to_screen(self, x_norm: float, y_norm: float) -> Tuple[float, float]:
        if self._homography is not None:
            pts = np.array([[[x_norm, y_norm]]], dtype=np.float32)
            mapped = cv2.perspectiveTransform(pts, self._homography)
            raw_x = float(mapped[0][0][0])
            raw_y = float(mapped[0][0][1])
            return raw_x, raw_y

        raw_x = x_norm * (self.screen_geometry.width - 1)
        raw_y = y_norm * (self.screen_geometry.height - 1)
        return raw_x, raw_y
