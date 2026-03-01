from google.adk.agents import Agent

from app.tools.browser import (
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

from app.callbacks.pointer import before_tool_inject_cursor


MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"

browser_agent = Agent(
    name="browser_agent",
    model=MODEL,
    description="Controls a Playwright browser session (navigate, scroll, pan/drag, click), supports 'here' via pointer cursor (hand/mouse).",
    instruction=(
        "You control a Playwright-driven Chromium page.\n\n"
        "Key idea: the user can point using a pointer cursor from hand tracking or mouse.\n"
        "When the user says 'here', 'this spot', 'right there', use the HERE tools.\n\n"
        "TOOLS:\n"
        "- navigate(url): open a URL inside the controlled browser.\n"
        "- pan(direction, amount=300): pan from viewport center.\n"
        "- click_here(): click at current pointer position.\n"
        "- scroll_here(delta_y, delta_x=0): wheel at current cursor position.\n"
        "- drag_here(dx, dy): drag starting at cursor by offsets.\n\n"
        "RULES:\n"
        "1) If user asks to open a page/site: navigate(url).\n"
        "2) If user says 'scroll up/down': use scroll_here(delta_y=...)\n"
        "3) If user says 'zoom in/out here' / 'zoom this area' / 'right there': use scroll_here().\n"
        "   - zoom in  => scroll_here(delta_y=-600)\n"
        "   - zoom out => scroll_here(delta_y=+600)\n"
        "4) If user says 'click here/right there': use click_here().\n"
        "5) If user says 'drag from here to the left/right/up/down': use drag_here(dx,dy).\n"
        "6) Keep confirmations short.\n"
    ),
    tools=[navigate, pan, click_here, scroll_here, drag_here],
    before_tool_callback=before_tool_inject_cursor,
)
