from __future__ import annotations

import asyncio
import base64
import io
from typing import Optional


async def take_screenshot(
    cursor_x: Optional[int] = None,
    cursor_y: Optional[int] = None,
    max_width: int = 1280,
) -> dict:
    """Capture a JPEG screenshot, optionally annotating cursor position."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _capture, cursor_x, cursor_y, max_width)


def _capture(cursor_x: Optional[int], cursor_y: Optional[int], max_width: int) -> dict:
    from PIL import ImageDraw, ImageGrab

    img = ImageGrab.grab()

    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)))
        if cursor_x is not None:
            cursor_x = int(cursor_x * ratio)
        if cursor_y is not None:
            cursor_y = int(cursor_y * ratio)

    if cursor_x is not None and cursor_y is not None:
        draw = ImageDraw.Draw(img)
        r = 18
        draw.ellipse(
            [cursor_x - r, cursor_y - r, cursor_x + r, cursor_y + r],
            outline="red",
            width=3,
        )
        draw.line([cursor_x - r, cursor_y, cursor_x + r, cursor_y], fill="red", width=2)
        draw.line([cursor_x, cursor_y - r, cursor_x, cursor_y + r], fill="red", width=2)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    return {
        "data": base64.b64encode(buf.getvalue()).decode(),
        "mime_type": "image/jpeg",
        "width": img.width,
        "height": img.height,
    }
