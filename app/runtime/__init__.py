from __future__ import annotations

from typing import Tuple


def _runtime_mod():
    # Lazy import to avoid loading Playwright for unrelated runtime helpers.
    from . import browser_runtime

    return browser_runtime


async def get_page(headless: bool = False, viewport: Tuple[int, int] = (1280, 800)):
    return await _runtime_mod().get_page(headless=headless, viewport=viewport)


async def get_viewport_origin_screen() -> Tuple[int, int]:
    return await _runtime_mod().get_viewport_origin_screen()


async def refresh_viewport_origin_screen() -> Tuple[int, int]:
    return await _runtime_mod().refresh_viewport_origin_screen()

async def get_browser_geometry():
    return await _runtime_mod().get_browser_geometry()


async def refresh_browser_geometry():
    return await _runtime_mod().refresh_browser_geometry()


def configure_headless_browser(
    viewport_width: int,
    viewport_height: int,
    origin_x: int,
    origin_y: int,
) -> None:
    _runtime_mod().configure_headless_browser(
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        origin_x=origin_x,
        origin_y=origin_y,
    )


__all__ = [
    "get_page",
    "get_viewport_origin_screen",
    "refresh_viewport_origin_screen",
    "get_browser_geometry",
    "refresh_browser_geometry",
    "configure_headless_browser",
]
