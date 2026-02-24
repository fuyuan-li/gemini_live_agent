import asyncio
from dataclasses import dataclass
from typing import Optional, Tuple

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright, CDPSession


@dataclass
class BrowserState:
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page
    cdp: CDPSession
    window_id: int
    # viewport top-left in *screen coords*
    viewport_origin: Tuple[int, int]


_state: Optional[BrowserState] = None
_lock = asyncio.Lock()


async def _compute_viewport_origin(page: Page, cdp: CDPSession) -> Tuple[Tuple[int, int], int]:
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

    return (origin_x, origin_y), window_id


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

        (origin_x, origin_y), window_id = await _compute_viewport_origin(page, cdp)

        _state = BrowserState(
            playwright=pw,
            browser=browser,
            context=context,
            page=page,
            cdp=cdp,
            window_id=window_id,
            viewport_origin=(origin_x, origin_y),
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
        return _state.viewport_origin  # type: ignore


async def refresh_viewport_origin_screen() -> Tuple[int, int]:
    """
    Recompute viewport origin in case user moved/resized the browser window.
    """
    global _state
    async with _lock:
        if _state is None:
            await get_page(headless=False)
        assert _state is not None
        (origin_x, origin_y), window_id = await _compute_viewport_origin(_state.page, _state.cdp)
        _state.window_id = window_id
        _state.viewport_origin = (origin_x, origin_y)
        return _state.viewport_origin


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