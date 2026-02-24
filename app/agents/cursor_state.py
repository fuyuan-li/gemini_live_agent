from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Tuple, Optional
import time
import asyncio

@dataclass
class Cursor:
    x: int
    y: int
    ts: float  # unix seconds

# keyed by (user_id, session_id)
_cursor: Dict[Tuple[str, str], Cursor] = {}
_lock = asyncio.Lock()

async def set_cursor(user_id: str, session_id: str, x: int, y: int) -> None:
    async with _lock:
        _cursor[(user_id, session_id)] = Cursor(x=int(x), y=int(y), ts=time.time())

async def get_cursor(user_id: str, session_id: str) -> Optional[Cursor]:
    async with _lock:
        return _cursor.get((user_id, session_id))