# app/tools/browser/mouse.py
import asyncio
from typing import Optional, Tuple

from google.adk.tools.tool_context import ToolContext

from app.runtime import get_page, refresh_viewport_origin_screen


# -----------------------------
# Basic mouse tools (no state)
# -----------------------------

async def click(x: int, y: int) -> dict:
    """
    Click at viewport coordinates (x, y).
    """
    page = await get_page(headless=False)
    await page.mouse.click(int(x), int(y))
    return {"ok": True, "action": "click", "x": int(x), "y": int(y), "url": page.url}


async def drag(x1: int, y1: int, x2: int, y2: int, steps: int = 30) -> dict:
    """
    Drag from (x1,y1) to (x2,y2) in viewport coordinates.
    Uses small delays + steps to emulate human drag for maps/canvas apps.
    """
    page = await get_page(headless=False)

    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
    steps = int(steps)

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
      - On map/canvas pages, wheel up/down often acts like zoom in/out.
      - On normal pages, wheel up/down scrolls content.

    delta_y < 0 => wheel up (often zoom in on maps)
    delta_y > 0 => wheel down (often zoom out on maps)
    """
    page = await get_page(headless=False)
    await page.mouse.wheel(int(delta_x), int(delta_y))
    return {
        "ok": True,
        "action": "scroll",
        "delta_x": int(delta_x),
        "delta_y": int(delta_y),
        "url": page.url,
    }


async def pan(direction: str, amount: int = 300) -> dict:
    """
    Pan by dragging from the viewport center. Does NOT require cursor state.
    """
    page = await get_page(headless=False)
    vp = page.viewport_size or {"width": 1280, "height": 800}
    cx, cy = int(vp["width"] // 2), int(vp["height"] // 2)

    d = direction.strip().lower()
    dx, dy = 0, 0
    amt = int(amount)

    if d in ("right", "east", "往右"):
        dx = amt
    elif d in ("left", "west", "往左"):
        dx = -amt
    elif d in ("up", "north", "往上"):
        dy = -amt
    elif d in ("down", "south", "往下"):
        dy = amt
    else:
        return {"ok": False, "error": f"Unknown direction: {direction}"}

    return await drag(cx, cy, cx + dx, cy + dy, steps=30)


# -----------------------------
# Cursor-driven tools (ToolContext.state)
# -----------------------------

def _get_cursor_from_state(tool_context: ToolContext) -> Optional[Tuple[int, int]]:
    """
    Read cursor from ADK session state.

    Expected:
      tool_context.state["cursor"] = {"x": int, "y": int, "ts": float}
    """
    current_session_state = tool_context.state or {}
    cur = current_session_state.get("cursor")
    print(f"[tool] Retrieved session state from tool_context.session: {current_session_state.to_dict()}")
    print(f"[tool] cursor raw = {cur}")
    if not isinstance(cur, dict):
        return None
    x = cur.get("x")
    y = cur.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    return int(x), int(y)


async def _cursor_screen_to_viewport(tool_context: ToolContext) -> Optional[Tuple[int, int]]:
    """
    Convert OS screen coords -> Playwright viewport coords using runtime window mapping.
    """
    cur =  _get_cursor_from_state(tool_context)
    if cur is None:
        return None

    page = await get_page(headless=False)
    origin_x, origin_y = await refresh_viewport_origin_screen()
    print(f"[tool] origin= {origin_x, origin_y}, cur={dir(cur)}")

    vx = int(cur[0] - origin_x)
    vy = int(cur[1] - origin_y)

    vp = page.viewport_size or {"width": 1280, "height": 800}
    vx = max(0, min(vx, int(vp["width"]) - 1))
    vy = max(0, min(vy, int(vp["height"]) - 1))
    return vx, vy


async def screen_to_viewport(x: int, y: int) -> Tuple[int, int]:
    """
    Convert OS screen coordinates into Playwright viewport coordinates.
    """
    page = await get_page(headless=False)
    origin_x, origin_y = await refresh_viewport_origin_screen()

    vx = int(int(x) - origin_x)
    vy = int(int(y) - origin_y)

    vp = page.viewport_size or {"width": 1280, "height": 800}
    vx = max(0, min(vx, int(vp["width"]) - 1))
    vy = max(0, min(vy, int(vp["height"]) - 1))
    return vx, vy


async def click_screen_point(x: int, y: int) -> dict:
    """
    Click using OS screen coordinates.
    """
    vx, vy = await screen_to_viewport(x, y)
    page = await get_page(headless=False)
    await page.mouse.click(vx, vy)
    return {"ok": True, "action": "click_here", "x": vx, "y": vy, "url": page.url}


async def scroll_screen_point(x: int, y: int, delta_y: int, delta_x: int = 0) -> dict:
    """
    Wheel scroll using OS screen coordinates.
    """
    vx, vy = await screen_to_viewport(x, y)
    page = await get_page(headless=False)
    await page.mouse.move(vx, vy)
    await page.mouse.wheel(int(delta_x), int(delta_y))
    return {
        "ok": True,
        "action": "scroll_here",
        "x": vx,
        "y": vy,
        "delta_x": int(delta_x),
        "delta_y": int(delta_y),
        "url": page.url,
    }


async def drag_screen_point_by_offset(x: int, y: int, dx: int, dy: int, steps: int = 30) -> dict:
    """
    Drag from an OS screen coordinate by viewport-relative offsets.
    """
    vx, vy = await screen_to_viewport(x, y)
    return await drag(vx, vy, vx + int(dx), vy + int(dy), steps=int(steps))


async def click_here(tool_context: ToolContext) -> dict:
    """
    Click at the current OS mouse cursor position ("here").
    """
    cur = _get_cursor_from_state(tool_context)
    if cur is None:
        return {"ok": False, "error": "No cursor in session state yet."}

    return await click_screen_point(cur[0], cur[1])


async def scroll_here(tool_context: ToolContext, delta_y: int, delta_x: int = 0) -> dict:
    """
    Wheel scroll at the current OS cursor position.
    Useful for 'zoom here' behavior on map/canvas apps.
    """
    cur = _get_cursor_from_state(tool_context)
    if cur is None:
        return {"ok": False, "error": "No cursor in session state yet."}

    return await scroll_screen_point(cur[0], cur[1], delta_y=int(delta_y), delta_x=int(delta_x))


async def drag_here(tool_context: ToolContext, dx: int, dy: int, steps: int = 30) -> dict:
    """
    Drag starting at current cursor position by (dx,dy) in viewport pixels.
    """
    cur = _get_cursor_from_state(tool_context)
    if cur is None:
        return {"ok": False, "error": "No cursor in session state yet."}

    return await drag_screen_point_by_offset(cur[0], cur[1], dx=int(dx), dy=int(dy), steps=int(steps))
