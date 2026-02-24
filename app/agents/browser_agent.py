from google.adk.agents import Agent

from app.tools.browser_tools import (
    navigate,
    screenshot_base64,
    click,
    drag,
    scroll,
    pan,
    click_here,
    scroll_here,
    drag_here,
)

MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"

browser_agent = Agent(
    name="browser_agent",
    model=MODEL,
    description="Controls a Playwright browser session (navigate, scroll, pan/drag, click), supports 'here' via OS mouse cursor.",
    instruction=(
        "You control a Playwright-driven Chromium page.\n\n"
        "Key idea: the user can point using their OS mouse cursor.\n"
        "When the user says 'here', 'this spot', 'right there', use the HERE tools.\n\n"
        "TOOLS:\n"
        "- navigate(url): open a URL inside the controlled browser.\n"
        "- scroll(delta_y, delta_x=0): wheel scroll. On map/canvas pages, wheel often means zoom in/out.\n"
        "- pan(direction, amount=300): pan from viewport center.\n"
        "- click(x,y), drag(x1,y1,x2,y2): explicit viewport-coordinate actions.\n"
        "- screenshot_base64(full_page=False): debugging.\n"
        "- click_here(): click at current OS mouse cursor position.\n"
        "- scroll_here(delta_y, delta_x=0): wheel at current cursor position.\n"
        "- drag_here(dx, dy): drag starting at cursor by offsets.\n\n"
        "RULES:\n"
        "1) If user asks to open a page/site: navigate(url).\n"
        "2) If user says 'scroll up/down': use scroll(delta_y=...)\n"
        "3) If user says 'zoom in/out here' / 'zoom this area' / 'right there': use scroll_here().\n"
        "   - zoom in  => scroll_here(delta_y=-600)\n"
        "   - zoom out => scroll_here(delta_y=+600)\n"
        "4) If user says 'click here/right there': use click_here().\n"
        "5) If user says 'drag from here to the left/right/up/down': use drag_here(dx,dy).\n"
        "6) Keep confirmations short.\n"
    ),
    tools=[navigate, screenshot_base64, click, drag, scroll, pan, click_here, scroll_here, drag_here],
)