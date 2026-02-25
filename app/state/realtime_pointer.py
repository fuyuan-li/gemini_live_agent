from __future__ import annotations

import asyncio
import time
from typing import Dict, Optional, Tuple, TypedDict


class CursorPayload(TypedDict):
    x: int
    y: int
    ts: float


_lock = asyncio.Lock()
_latest_cursor: Dict[Tuple[str, str], CursorPayload] = {}


async def set_cursor(user_id: str, session_id: str, x: int, y: int) -> None:
    async with _lock:
        _latest_cursor[(user_id, session_id)] = {"x": int(x), "y": int(y), "ts": time.time()}


async def get_cursor(user_id: str, session_id: str) -> Optional[CursorPayload]:
    async with _lock:
        return _latest_cursor.get((user_id, session_id))