import asyncio
from dataclasses import dataclass
from typing import Optional, Tuple

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright


@dataclass
class BrowserState:
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page


_state: Optional[BrowserState] = None
_lock = asyncio.Lock()


async def get_page(headless: bool = False, viewport: Tuple[int, int] = (1280, 800)) -> Page:
    """
    Lazily create a persistent Playwright browser + page, and reuse it across tool calls.
    """
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
        _state = BrowserState(playwright=pw, browser=browser, context=context, page=page)
        return page


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