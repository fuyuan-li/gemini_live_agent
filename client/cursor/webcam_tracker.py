from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional, Tuple

import cv2  # type: ignore
import mediapipe as mp  # type: ignore
from mediapipe.tasks import python as mp_tasks_python  # type: ignore
from mediapipe.tasks.python import vision as mp_vision  # type: ignore

from .mapper import get_main_display_size
from .types import NormalizedSample, TrackerHealth

MODEL_DOWNLOAD_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
)
def _bundled_model_path() -> Path:
    return Path(__file__).resolve().parents[1] / "models" / "hand_landmarker.task"


def _resolve_model_path() -> Path:
    path = _bundled_model_path()
    if not path.exists():
        raise FileNotFoundError(
            "bundled hand landmarker model missing. "
            f"Expected read-only asset at: {path}"
        )
    return path


class WebcamFingerTracker:
    """
    Detect index fingertip in webcam frames and output normalized coordinates.

    Frame processing runs in a worker thread. Preview rendering stays on the
    main thread via pump_preview(), which reads the cached preview frame and
    hands it to cv2.imshow().
    """

    def __init__(
        self,
        camera_index: int = 0,
        mirror: bool = True,
        preview_enabled: bool = True,
        min_detection_confidence: float = 0.6,
        min_tracking_confidence: float = 0.5,
        index_tip_id: int = 8,
        num_hands: int = 1,
        preview_scale: float = 0.24,
        preview_margin: int = 24,
    ) -> None:
        self.camera_index = int(camera_index)
        self.mirror = bool(mirror)
        self.preview_enabled = bool(preview_enabled)

        self.min_detection_confidence = float(min_detection_confidence)
        self.min_tracking_confidence = float(min_tracking_confidence)
        self.index_tip_id = int(index_tip_id)
        self.num_hands = int(max(1, num_hands))
        self.preview_scale = float(min(0.9, max(0.1, preview_scale)))
        self.preview_margin = int(max(0, preview_margin))

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._running = False
        self._last_error: Optional[str] = None
        self._latest: Optional[NormalizedSample] = None
        self._last_seen_ts: Optional[float] = None
        self._frames_seen = 0

        self._preview_window_name = "Hand Cursor Preview"
        self._preview_window_open = False
        self._preview_frame = None

    def start(self, timeout_s: float = 3.0) -> bool:
        if self._thread and self._thread.is_alive():
            return True

        self._last_error = None
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

        deadline = time.time() + max(0.1, timeout_s)
        while time.time() < deadline:
            if self._running:
                return True
            if self._last_error:
                return False
            if self._thread and not self._thread.is_alive():
                self._last_error = self._last_error or "tracker thread exited during startup"
                return False
            time.sleep(0.02)

        if self._thread and self._thread.is_alive() and self._last_error is None:
            return True

        self._last_error = self._last_error or f"tracker startup timed out after {timeout_s:.1f}s"
        return False

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self.close_preview_window()

    def is_running(self) -> bool:
        return self._running

    def get_last_error(self) -> Optional[str]:
        return self._last_error

    def get_latest_sample(self) -> Optional[NormalizedSample]:
        with self._lock:
            return self._latest

    def get_preview_frame(self):
        with self._lock:
            if self._preview_frame is None:
                return None
            return self._preview_frame.copy()

    def get_health(self) -> TrackerHealth:
        with self._lock:
            return TrackerHealth(
                running=self._running,
                last_error=self._last_error,
                last_seen_ts=self._last_seen_ts,
                frames_seen=self._frames_seen,
            )

    def pump_preview(self) -> None:
        if not self.preview_enabled:
            if self._preview_window_open:
                self.close_preview_window()
            return

        frame = self.get_preview_frame()
        if frame is None:
            return

        try:
            if not self._preview_window_open:
                cv2.namedWindow(self._preview_window_name, cv2.WINDOW_NORMAL)
                height, width = frame.shape[:2]
                preview_w = max(180, int(width * self.preview_scale))
                preview_h = max(120, int(height * self.preview_scale))
                cv2.resizeWindow(self._preview_window_name, preview_w, preview_h)

                screen_w, screen_h = get_main_display_size()
                pos_x = max(0, screen_w - preview_w - self.preview_margin)
                pos_y = max(0, screen_h - preview_h - self.preview_margin)
                cv2.moveWindow(self._preview_window_name, pos_x, pos_y)
                self._preview_window_open = True

            cv2.imshow(self._preview_window_name, frame)
            cv2.waitKey(1)
        except Exception as exc:
            self._last_error = str(exc)

    def close_preview_window(self) -> None:
        if self._preview_window_open:
            try:
                cv2.destroyWindow(self._preview_window_name)
            except Exception:
                pass
            self._preview_window_open = False

    def _create_landmarker(self):
        model_path = _resolve_model_path()
        options = mp_vision.HandLandmarkerOptions(
            base_options=mp_tasks_python.BaseOptions(model_asset_path=str(model_path)),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_hands=self.num_hands,
            min_hand_detection_confidence=self.min_detection_confidence,
            min_hand_presence_confidence=self.min_tracking_confidence,
            min_tracking_confidence=self.min_tracking_confidence,
        )
        return mp_vision.HandLandmarker.create_from_options(options)

    def _detect_fingertip(self, frame_bgr, landmarker) -> Optional[Tuple[float, float, float]]:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        ts_ms = int(time.monotonic() * 1000)

        result = landmarker.detect_for_video(mp_image, ts_ms)
        if not result.hand_landmarks:
            return None

        landmarks = result.hand_landmarks[0]
        if not 0 <= self.index_tip_id < len(landmarks):
            return None

        tip = landmarks[self.index_tip_id]
        score = 1.0
        if result.handedness and result.handedness[0]:
            score = float(result.handedness[0][0].score)

        return (
            min(1.0, max(0.0, float(tip.x))),
            min(1.0, max(0.0, float(tip.y))),
            score,
        )

    def _run(self) -> None:
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            self._last_error = f"failed to open camera index {self.camera_index}"
            self._running = False
            return

        landmarker = None
        try:
            landmarker = self._create_landmarker()
            self._running = True

            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.01)
                    continue

                if self.mirror:
                    frame = cv2.flip(frame, 1)

                result = self._detect_fingertip(frame, landmarker)
                preview_frame = frame.copy() if self.preview_enabled else None

                if result is not None:
                    x_norm, y_norm, score = result
                    sample = NormalizedSample(
                        x=x_norm,
                        y=y_norm,
                        ts=time.time(),
                        confidence=score,
                    )
                    with self._lock:
                        self._latest = sample
                        self._last_seen_ts = sample.ts
                        self._frames_seen += 1

                    if preview_frame is not None:
                        height, width = preview_frame.shape[:2]
                        px = int(x_norm * (width - 1))
                        py = int(y_norm * (height - 1))
                        cv2.circle(preview_frame, (px, py), 10, (0, 255, 255), -1)

                if preview_frame is not None:
                    with self._lock:
                        self._preview_frame = preview_frame
        except Exception as exc:
            self._last_error = str(exc)
        finally:
            self._running = False
            if landmarker is not None:
                try:
                    landmarker.close()
                except Exception:
                    pass
            cap.release()
