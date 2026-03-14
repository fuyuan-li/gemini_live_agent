from __future__ import annotations

import asyncio
import base64
import io
from typing import Optional


async def take_screenshot(
    cursor_x: Optional[int] = None,
    cursor_y: Optional[int] = None,
    max_width: int = 768,
) -> dict:
    """
    Capture a JPEG screenshot of the browser viewport, annotating cursor position.

    In headless embedded mode, uses Playwright page.screenshot() so the AI sees
    exactly the browser content (not the companion app's physical window frame).
    Falls back to ImageGrab for non-headless mode.
    """
    try:
        from app.runtime import browser_runtime as _br
        if _br._headless_mode and _br._state is not None:
            return await _playwright_screenshot(
                _br._state.page,
                cursor_x,
                cursor_y,
                max_width,
                _br._viewport_origin_override,
            )
    except Exception:
        pass

    # Fallback: physical screen capture
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _capture, cursor_x, cursor_y, max_width)


async def _playwright_screenshot(
    page,
    cursor_x: Optional[int],
    cursor_y: Optional[int],
    max_width: int,
    origin_override,
) -> dict:
    """Screenshot directly from Playwright viewport with cursor annotation."""
    from PIL import Image, ImageDraw  # type: ignore

    # Use a reduced scale to stay well under Gemini Live's inline-image size limit.
    # Full-viewport at 1x produces 300-500KB base64, which triggers error 1007.
    raw = await page.screenshot(type="jpeg", quality=55, scale="css")
    img = Image.open(io.BytesIO(raw))

    # Convert screen-space cursor coords → viewport coords
    vp_x: Optional[int] = None
    vp_y: Optional[int] = None
    if cursor_x is not None and cursor_y is not None:
        if origin_override is not None:
            ox, oy = origin_override
            vp_x = int(cursor_x) - int(ox)
            vp_y = int(cursor_y) - int(oy)
        else:
            vp_x = int(cursor_x)
            vp_y = int(cursor_y)

    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)))
        if vp_x is not None:
            vp_x = int(vp_x * ratio)
            vp_y = int(vp_y * ratio)  # type: ignore[assignment]

    img = img.convert("RGB")

    if vp_x is not None and vp_y is not None:
        draw = ImageDraw.Draw(img)
        r = 18
        draw.ellipse([vp_x - r, vp_y - r, vp_x + r, vp_y + r], outline="red", width=3)
        draw.line([vp_x - r, vp_y, vp_x + r, vp_y], fill="red", width=2)
        draw.line([vp_x, vp_y - r, vp_x, vp_y + r], fill="red", width=2)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=55)
    return {
        "data": base64.b64encode(buf.getvalue()).decode(),
        "mime_type": "image/jpeg",
        "width": img.width,
        "height": img.height,
    }


def _capture(cursor_x: Optional[int], cursor_y: Optional[int], max_width: int) -> dict:
    from PIL import ImageDraw, ImageGrab  # type: ignore

    img = ImageGrab.grab()

    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)))
        if cursor_x is not None:
            cursor_x = int(cursor_x * ratio)
        if cursor_y is not None:
            cursor_y = int(cursor_y * ratio)

    img = img.convert("RGB")

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
