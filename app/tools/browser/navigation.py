from app.runtime import get_page


async def navigate(url: str) -> dict:
    """
    Navigate the controlled browser to a URL inside the Playwright-controlled Chromium page.
    """
    url = url.strip()
    if not url:
        return {"ok": False, "error": "Empty URL"}
    if "://" not in url:
        url = "https://" + url

    page = await get_page(headless=False)
    await page.goto(url, wait_until="domcontentloaded")
    return {"ok": True, "url": page.url, "title": await page.title()}