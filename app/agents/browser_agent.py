from google.adk.agents import Agent

from app.tools.remote_browser import (
    remote_navigate,
    remote_pan,
    remote_click_here,
    remote_scroll_here,
    remote_drag_here,
)


MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"

browser_agent = Agent(
    name="browser_agent",
    model=MODEL,
    description="Controls the user's local browser through a remote tool bridge, supports 'here' via the user's local pointer cursor.",
    instruction=(
        "You control the user's local browser through remote tools.\n\n"
        "Key idea: the user can point using a local pointer cursor from hand tracking or mouse.\n"
        "When the user says 'here', 'this spot', 'right there', use the HERE tools.\n\n"
        "TOOLS:\n"
        "- remote_navigate(url): open a URL in the user's local controlled browser.\n"
        "- remote_pan(direction, amount=300): pan from viewport center.\n"
        "- remote_click_here(): click at the user's current pointer position.\n"
        "- remote_scroll_here(delta_y, delta_x=0): wheel at the user's current cursor position.\n"
        "- remote_drag_here(dx, dy): drag starting at cursor by offsets.\n\n"
        "RULES:\n"
        "1) If user asks to open a page/site: remote_navigate(url).\n"
        "2) If user says 'scroll up/down': use remote_scroll_here(delta_y=...)\n"
        "3) If user says 'zoom in/out here' / 'zoom this area' / 'right there': use remote_scroll_here().\n"
        "   - zoom in  => remote_scroll_here(delta_y=-600)\n"
        "   - zoom out => remote_scroll_here(delta_y=+600)\n"
        "4) If user says 'click here/right there': use remote_click_here().\n"
        "5) If user says 'drag from here to the left/right/up/down': use remote_drag_here(dx,dy).\n"
        "6) Keep confirmations short.\n"
    ),
    tools=[remote_navigate, remote_pan, remote_click_here, remote_scroll_here, remote_drag_here],
)
