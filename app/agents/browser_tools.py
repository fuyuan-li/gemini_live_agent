import base64
import asyncio
from typing import Optional

from .cursor_state import get_cursor
from .browser_runtime import get_page, get_viewport_origin_screen, refresh_viewport_origin_screen


async def navigate(url: str) -> dict:
    """
    Navigate the controlled browser to a URL.

    Notes:
      - This opens the URL inside the Playwright-controlled Chromium page
        (NOT the system default browser).
    """
    url = url.strip()
    if not url:
        return {"ok": False, "error": "Empty URL"}
    if "://" not in url:
        url = "https://" + url

    page = await get_page(headless=False)
    await page.goto(url, wait_until="domcontentloaded")
    return {"ok": True, "url": page.url, "title": await page.title()}


async def screenshot_base64(full_page: bool = False) -> dict:
    """
    Take a screenshot of the current page and return it as base64 PNG.

    This is useful for debugging and for future "vision-in-the-loop" browsing.
    """
    page = await get_page(headless=False)
    png_bytes = await page.screenshot(full_page=full_page, type="png")
    b64 = base64.b64encode(png_bytes).decode("utf-8")
    return {"ok": True, "png_base64": b64, "url": page.url}


async def click(x: int, y: int) -> dict:
    """
    Click at viewport coordinates (x, y).

    Coordinates are in pixels relative to the top-left of the current viewport.
    """
    page = await get_page(headless=False)
    await page.mouse.click(x, y)
    return {"ok": True, "action": "click", "x": x, "y": y, "url": page.url}


async def drag(x1: int, y1: int, x2: int, y2: int, steps: int = 25) -> dict:
    """
    Drag from (x1, y1) to (x2, y2) in viewport coordinates.

    Many canvas/map apps (e.g., Google Maps) are sensitive to drag smoothness.
    We move with 'steps' and small delays to better emulate a human drag.
    """
    page = await get_page(headless=False)

    await page.mouse.move(x1, y1)
    await asyncio.sleep(0.03)

    await page.mouse.down()
    await asyncio.sleep(0.03)

    await page.mouse.move(x2, y2, steps=steps)
    await asyncio.sleep(0.03)

    await page.mouse.up()

    return {
        "ok": True,
        "action": "drag",
        "from": [x1, y1],
        "to": [x2, y2],
        "steps": steps,
        "url": page.url,
    }


async def scroll(delta_y: int, delta_x: int = 0) -> dict:
    """
    Scroll the viewport using the mouse wheel.

    IMPORTANT SEMANTICS:
      - On map-like pages (e.g., Google Maps), scrolling up/down is commonly
        interpreted as ZOOM IN / ZOOM OUT (i.e., changes the map zoom level).
      - On normal web pages, scrolling up/down is interpreted as PAGE SCROLL
        (i.e., moves the page content).

    Args:
      delta_y: Vertical wheel delta in pixels-ish units.
               Negative => wheel up (often "zoom in" on maps, or scroll up on pages).
               Positive => wheel down (often "zoom out" on maps, or scroll down on pages).
      delta_x: Horizontal wheel delta.

    Returns:
      A dict describing the performed action.
    """
    page = await get_page(headless=False)
    await page.mouse.wheel(delta_x, delta_y)
    return {
        "ok": True,
        "action": "scroll",
        "delta_x": delta_x,
        "delta_y": delta_y,
        "url": page.url,
    }


async def pan(direction: str, amount: int = 300) -> dict:
    """
    Pan the view by dragging from the center of the viewport in a direction.

    This is a convenience wrapper around drag() so the agent can respond to
    instructions like "pan left", "move right", "drag up a bit" without needing
    explicit coordinates.

    Args:
      direction: one of {"left","right","up","down"} (case-insensitive).
      amount: pixel distance to drag.

    Returns:
      A dict describing the performed action.
    """
    page = await get_page(headless=False)
    vp = page.viewport_size or {"width": 1280, "height": 800}
    cx, cy = vp["width"] // 2, vp["height"] // 2

    d = direction.strip().lower()
    dx, dy = 0, 0
    if d in ("right", "east", "往右"):
        dx = amount
    elif d in ("left", "west", "往左"):
        dx = -amount
    elif d in ("up", "north", "往上"):
        dy = -amount
    elif d in ("down", "south", "往下"):
        dy = amount
    else:
        return {"ok": False, "error": f"Unknown direction: {direction}"}

    return await drag(cx, cy, cx + dx, cy + dy, steps=30)


async def _move_to_cursor(user_id: str, session_id: str):
    cur = await get_cursor(user_id, session_id)
    if cur is None:
        return None

    page = await get_page(headless=False)
    origin_x, origin_y = await refresh_viewport_origin_screen()
    # origin_x, origin_y = await get_viewport_origin_screen()

    # screen -> viewport
    vx = int(cur.x - origin_x)
    vy = int(cur.y - origin_y)

    # 可选：clamp 到 viewport 内
    vp = page.viewport_size or {"width": 1280, "height": 800}
    vx = max(0, min(vx, vp["width"] - 1))
    vy = max(0, min(vy, vp["height"] - 1))

    await page.mouse.move(vx, vy)
    return (vx, vy)


async def click_cursor(user_id: str, session_id: str) -> dict:
    """
    Click at the current OS cursor position.
    """
    pos = await _move_to_cursor(user_id, session_id)
    if pos is None:
        return {"ok": False, "error": "No cursor position received yet."}
    page = await get_page(headless=False)
    await page.mouse.click(pos[0], pos[1])
    return {"ok": True, "action": "click_cursor", "x": pos[0], "y": pos[1], "url": page.url}


async def scroll_cursor(user_id: str, session_id: str, delta_y: int, delta_x: int = 0) -> dict:
    """
    Scroll (wheel) at the current OS cursor position.
    Useful for 'zoom here' behavior on map/canvas apps.
    """
    pos = await _move_to_cursor(user_id, session_id)
    if pos is None:
        return {"ok": False, "error": "No cursor position received yet."}
    page = await get_page(headless=False)
    await page.mouse.wheel(delta_x, delta_y)
    return {
        "ok": True,
        "action": "scroll_cursor",
        "x": pos[0],
        "y": pos[1],
        "delta_x": delta_x,
        "delta_y": delta_y,
        "url": page.url,
    }


async def drag_cursor(user_id: str, session_id: str, dx: int, dy: int, steps: int = 30) -> dict:
    """
    Drag starting from cursor position by (dx, dy).
    """
    pos = await _move_to_cursor(user_id, session_id)
    if pos is None:
        return {"ok": False, "error": "No cursor position received yet."}
    x1, y1 = pos
    x2, y2 = x1 + dx, y1 + dy
    return await drag(x1, y1, x2, y2, steps=steps)
