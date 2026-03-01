from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple


def parse_cursor_payload(payload: Mapping[str, Any]) -> Optional[Tuple[int, int]]:
    """
    Parse cursor control payload and return (x, y).

    Required fields:
      - type == "cursor"
      - x, y numeric

    Optional fields are ignored for forward compatibility:
      - source, confidence, ts
    """
    if payload.get("type") != "cursor":
        return None

    x = payload.get("x")
    y = payload.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None

    return int(x), int(y)
