import asyncio
from dataclasses import dataclass
from typing import Optional, Tuple

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright, CDPSession

from client.cursor.displays import get_display_for_rect


@dataclass(frozen=True)
class WindowBounds:
    left: int
    top: int
    width: int
    height: int


@dataclass(frozen=True)
class BrowserGeometry:
    window_bounds: WindowBounds
    viewport_origin: Tuple[int, int]
    viewport_size: Tuple[int, int]
    display_id: Optional[int]

@dataclass
class BrowserState:
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page
    cdp: CDPSession
    window_id: int
    geometry: BrowserGeometry


_state: Optional[BrowserState] = None
_lock = asyncio.Lock()


async def _compute_browser_geometry(page: Page, cdp: CDPSession) -> Tuple[BrowserGeometry, int]:
    """
    Compute viewport top-left origin in screen coordinates.

    - CDP gives outer window bounds: left, top, width, height (includes chrome/title bar/borders).
    - Playwright viewport_size is the page's inner content area.

    We approximate:
      border_x = (outer_w - vp_w) / 2
      chrome_top = outer_h - vp_h - border_x   (assume bottom border ~ border_x)
    Then:
      origin_x = left + border_x
      origin_y = top + chrome_top
    """
    # 1) Get window bounds from CDP
    target = await cdp.send("Target.getTargetInfo")
    target_id = target["targetInfo"]["targetId"]

    win_info = await cdp.send("Browser.getWindowForTarget", {"targetId": target_id})
    window_id = win_info["windowId"]

    bounds = await cdp.send("Browser.getWindowBounds", {"windowId": window_id})
    b = bounds["bounds"]

    left = int(b.get("left", 0))
    top = int(b.get("top", 0))
    outer_w = int(b.get("width", 0))
    outer_h = int(b.get("height", 0))

    vp = page.viewport_size or {"width": 1280, "height": 800}
    vp_w = int(vp["width"])
    vp_h = int(vp["height"])

    # 2) Approximate borders + chrome
    border_x = max(0, int(round((outer_w - vp_w) / 2)))
    chrome_top = max(0, outer_h - vp_h - border_x)

    origin_x = left + border_x
    origin_y = top + chrome_top

    window_bounds = WindowBounds(left=left, top=top, width=outer_w, height=outer_h)
    display = get_display_for_rect(left, top, outer_w, outer_h)
    geometry = BrowserGeometry(
        window_bounds=window_bounds,
        viewport_origin=(origin_x, origin_y),
        viewport_size=(vp_w, vp_h),
        display_id=None if display is None else int(display.display_id),
    )
    return geometry, window_id


async def get_page(headless: bool = False, viewport: Tuple[int, int] = (1280, 800)) -> Page:
    global _state
    async with _lock:
        if _state is not None:
            return _state.page

        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]},
        )
        page = await context.new_page()

        cdp = await context.new_cdp_session(page)

        geometry, window_id = await _compute_browser_geometry(page, cdp)

        _state = BrowserState(
            playwright=pw,
            browser=browser,
            context=context,
            page=page,
            cdp=cdp,
            window_id=window_id,
            geometry=geometry,
        )
        return page


async def get_viewport_origin_screen() -> Tuple[int, int]:
    """
    Return cached viewport origin in screen coords.
    """
    global _state
    async with _lock:
        if _state is None:
            # force init
            page = await get_page(headless=False)
        return _state.geometry.viewport_origin  # type: ignore


async def get_browser_geometry() -> BrowserGeometry:
    global _state
    async with _lock:
        if _state is None:
            await get_page(headless=False)
        assert _state is not None
        return _state.geometry


async def refresh_browser_geometry() -> BrowserGeometry:
    """
    Recompute browser geometry in case user moved/resized the browser window.
    """
    global _state
    async with _lock:
        if _state is None:
            await get_page(headless=False)
        assert _state is not None
        geometry, window_id = await _compute_browser_geometry(_state.page, _state.cdp)
        _state.window_id = window_id
        _state.geometry = geometry
        return _state.geometry


async def refresh_viewport_origin_screen() -> Tuple[int, int]:
    geometry = await refresh_browser_geometry()
    return geometry.viewport_origin


async def shutdown() -> None:
    global _state
    async with _lock:
        if _state is None:
            return
        try:
            await _state.context.close()
        except Exception:
            pass
        try:
            await _state.browser.close()
        except Exception:
            pass
        try:
            await _state.playwright.stop()
        except Exception:
            pass
        _state = None
