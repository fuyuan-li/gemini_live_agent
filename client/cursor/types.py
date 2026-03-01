from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


CursorSource = Literal["hand", "mouse"]


@dataclass(frozen=True)
class NormalizedSample:
    x: float
    y: float
    ts: float
    confidence: Optional[float] = None


@dataclass(frozen=True)
class CursorSample:
    x: int
    y: int
    ts: float
    source: CursorSource
    confidence: Optional[float] = None


@dataclass(frozen=True)
class TrackerHealth:
    running: bool
    last_error: Optional[str]
    last_seen_ts: Optional[float]
    frames_seen: int
