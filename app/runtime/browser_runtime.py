import asyncio
import base64
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

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

# --- Headless embedded browser configuration ---
_headless_mode: bool = False
_viewport_origin_override: Optional[Tuple[int, int]] = None
_headless_viewport_size: Optional[Tuple[int, int]] = None
_screencast_frame: Optional[bytes] = None
_screencast_active: bool = False
_screencast_frame_callbacks: list[Callable[[bytes], None]] = []


def configure_headless_browser(
    viewport_width: int,
    viewport_height: int,
    origin_x: int,
    origin_y: int,
) -> None:
    """
    Call from companion_app before the browser starts to configure embedded headless mode.
    viewport_width/height: size of the browser view in logical screen pixels.
    origin_x/origin_y: top-left of the browser view in Quartz screen coordinates.
    """
    global _headless_mode, _viewport_origin_override, _headless_viewport_size
    _headless_mode = True
    _viewport_origin_override = (int(origin_x), int(origin_y))
    _headless_viewport_size = (int(viewport_width), int(viewport_height))


def get_latest_screencast_frame() -> Optional[bytes]:
    """Return the latest JPEG frame from the CDP screencast, or None if not yet available."""
    return _screencast_frame


def add_screencast_frame_callback(cb: Callable[[bytes], None]) -> None:
    """Register a callback to be called (from the asyncio thread) on each new screencast frame."""
    _screencast_frame_callbacks.append(cb)


async def forward_mouse_click(vp_x: int, vp_y: int) -> None:
    """Click at viewport coordinates in the headless browser."""
    if _state is not None:
        await _state.page.mouse.click(int(vp_x), int(vp_y))


async def forward_mouse_move(vp_x: int, vp_y: int) -> None:
    """Move mouse to viewport coordinates in the headless browser."""
    if _state is not None:
        await _state.page.mouse.move(int(vp_x), int(vp_y))


async def forward_scroll(vp_x: int, vp_y: int, delta_x: int, delta_y: int) -> None:
    """Scroll at viewport coordinates in the headless browser."""
    if _state is not None:
        await _state.page.mouse.move(int(vp_x), int(vp_y))
        await _state.page.mouse.wheel(int(delta_x), int(delta_y))


async def _start_screencast(cdp: CDPSession, width: int, height: int) -> None:
    global _screencast_active, _screencast_frame

    if _screencast_active:
        return
    _screencast_active = True

    async def _on_frame(event: dict) -> None:
        global _screencast_frame
        data = event.get("data", "")
        if data:
            try:
                _screencast_frame = base64.b64decode(data)
                for cb in _screencast_frame_callbacks:
                    try:
                        cb(_screencast_frame)
                    except Exception:
                        pass
            except Exception:
                pass
        session_id = event.get("sessionId")
        if session_id is not None:
            try:
                await cdp.send("Page.screencastFrameAck", {"sessionId": session_id})
            except Exception:
                pass

    cdp.on("Page.screencastFrame", _on_frame)
    try:
        await cdp.send("Page.startScreencast", {
            "format": "jpeg",
            "quality": 75,
            "maxWidth": width,
            "maxHeight": height,
        })
    except Exception:
        _screencast_active = False


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

    # 2) Determine viewport origin in screen coordinates.
    # In headless embedded mode, use the configured override (position of the NSImageView).
    if _viewport_origin_override is not None:
        origin_x, origin_y = _viewport_origin_override
    else:
        # Approximate borders + chrome for a visible browser window
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

        # Headless embedded mode overrides caller's settings
        if _headless_mode:
            headless = True
        if _headless_viewport_size is not None:
            viewport = _headless_viewport_size

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

        # Auto-start screencast in headless embedded mode
        if _headless_mode:
            asyncio.create_task(_start_screencast(cdp, viewport[0], viewport[1]))

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
    global _state, _screencast_active, _screencast_frame
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
        _screencast_active = False
        _screencast_frame = None
