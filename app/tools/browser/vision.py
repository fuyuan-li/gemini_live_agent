import base64
from app.runtime import get_page


async def screenshot_base64(full_page: bool = False) -> dict:
    """
    Take a screenshot and return base64 PNG.
    (Useful for debugging & future vision-in-the-loop browsing.)
    """
    page = await get_page(headless=False)
    png_bytes = await page.screenshot(full_page=full_page, type="png")
    b64 = base64.b64encode(png_bytes).decode("utf-8")
    return {"ok": True, "png_base64": b64, "url": page.url}