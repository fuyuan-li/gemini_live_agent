from app.runtime import get_page


async def play_pause() -> dict:
    page = await get_page(headless=False)
    result = await page.evaluate("""() => {
        const video = document.querySelector('video');
        if (!video) return {ok: false, error: 'No video element found on this page.'};
        if (video.paused) { video.play(); return {ok: true, state: 'playing'}; }
        else { video.pause(); return {ok: true, state: 'paused'}; }
    }""")
    return result
