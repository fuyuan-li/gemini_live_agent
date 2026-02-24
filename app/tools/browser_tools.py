import base64
import asyncio
from typing import Optional, Tuple

from google.adk.tools import ToolContext

from ..runtime.browser_runtime import (
    get_page,
    refresh_viewport_origin_screen,
)


async def navigate(url: str) -> dict:
    """
    Navigate the controlled browser to a URL.
    This opens the URL inside the Playwright-controlled Chromium page (NOT system browser).
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
    """Return a base64 PNG screenshot (debugging / future vision-in-the-loop)."""
    page = await get_page(headless=False)
    png_bytes = await page.screenshot(full_page=full_page, type="png")
    b64 = base64.b64encode(png_bytes).decode("utf-8")
    return {"ok": True, "png_base64": b64, "url": page.url}


async def click(x: int, y: int) -> dict:
    """Click at viewport coordinates (x, y)."""
    page = await get_page(headless=False)
    await page.mouse.click(x, y)
    return {"ok": True, "action": "click", "x": x, "y": y, "url": page.url}


async def drag(x1: int, y1: int, x2: int, y2: int, steps: int = 30) -> dict:
    """Drag from (x1,y1) to (x2,y2) in viewport coords, with steps to emulate human drag."""
    page = await get_page(headless=False)

    await page.mouse.move(x1, y1)
    await asyncio.sleep(0.03)

    await page.mouse.down()
    await asyncio.sleep(0.03)

    await page.mouse.move(x2, y2, steps=steps)
    await asyncio.sleep(0.03)

    await page.mouse.up()

    return {"ok": True, "action": "drag", "from": [x1, y1], "to": [x2, y2], "steps": steps, "url": page.url}


async def scroll(delta_y: int, delta_x: int = 0) -> dict:
    """
    Mouse wheel scroll.

    IMPORTANT SEMANTICS:
      - On map/canvas pages, wheel up/down is often interpreted as zoom in/out.
      - On normal pages, wheel up/down scrolls the page.
    """
    page = await get_page(headless=False)
    await page.mouse.wheel(delta_x, delta_y)
    return {"ok": True, "action": "scroll", "delta_x": delta_x, "delta_y": delta_y, "url": page.url}


async def pan(direction: str, amount: int = 300) -> dict:
    """Pan by dragging from viewport center (no cursor needed)."""
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


# -----------------------------
# Cursor-driven tools (ToolContext.state)
# -----------------------------

def _get_cursor_from_tool_state(tool_context: ToolContext) -> Optional[Tuple[int, int]]:
    """
    Read cursor from ADK session state via ToolContext.

    Expected state shape:
      tool_context.state["cursor"] = {"x": int, "y": int, "ts": float}
    """
    cur = tool_context.state.get("cursor")
    if not isinstance(cur, dict):
        return None
    x = cur.get("x")
    y = cur.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    return int(x), int(y)


async def _cursor_screen_to_viewport(tool_context: ToolContext) -> Optional[Tuple[int, int]]:
    """
    Convert OS screen coords -> Playwright viewport coords using runtime mapping.
    """
    cur = _get_cursor_from_tool_state(tool_context)
    if cur is None:
        return None

    page = await get_page(headless=False)
    origin_x, origin_y = await refresh_viewport_origin_screen()

    vx = int(cur[0] - origin_x)
    vy = int(cur[1] - origin_y)

    # clamp
    vp = page.viewport_size or {"width": 1280, "height": 800}
    vx = max(0, min(vx, int(vp["width"]) - 1))
    vy = max(0, min(vy, int(vp["height"]) - 1))
    return vx, vy


async def click_here(tool_context: ToolContext) -> dict:
    """
    Click at the current OS mouse cursor position ("here").
    """
    pos = await _cursor_screen_to_viewport(tool_context)
    if pos is None:
        return {"ok": False, "error": "No cursor found in session state yet."}

    page = await get_page(headless=False)
    await page.mouse.click(pos[0], pos[1])
    return {"ok": True, "action": "click_here", "x": pos[0], "y": pos[1], "url": page.url}


async def scroll_here(tool_context: ToolContext, delta_y: int, delta_x: int = 0) -> dict:
    """
    Wheel scroll at the current OS mouse cursor position.
    Useful for map/canvas zoom-at-point behavior.
    """
    pos = await _cursor_screen_to_viewport(tool_context)
    if pos is None:
        return {"ok": False, "error": "No cursor found in session state yet."}

    page = await get_page(headless=False)
    await page.mouse.move(pos[0], pos[1])
    await page.mouse.wheel(delta_x, delta_y)
    return {
        "ok": True,
        "action": "scroll_here",
        "x": pos[0],
        "y": pos[1],
        "delta_x": delta_x,
        "delta_y": delta_y,
        "url": page.url,
    }


async def drag_here(tool_context: ToolContext, dx: int, dy: int, steps: int = 30) -> dict:
    """
    Drag starting from the current OS mouse cursor position by (dx, dy).
    """
    pos = await _cursor_screen_to_viewport(tool_context)
    if pos is None:
        return {"ok": False, "error": "No cursor found in session state yet."}

    x1, y1 = pos
    x2, y2 = x1 + int(dx), y1 + int(dy)
    return await drag(x1, y1, x2, y2, steps=steps)