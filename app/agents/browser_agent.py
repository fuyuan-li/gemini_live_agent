# app/agents/browser_agent.py
from google.adk.agents import Agent
from .browser_tools import (
    navigate,
    screenshot_base64,
    click,
    drag,
    scroll,
    pan,
    click_cursor,
    scroll_cursor,
    drag_cursor,
)

MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"

browser_agent = Agent(
    name="browser_agent",
    model=MODEL,
    description="Controls a Playwright browser session (navigate, scroll, pan/drag, click).",
    instruction=(
        "You are a browser operator controlling a Playwright-driven Chromium page.\n\n"
        "Key idea: the user can point using their OS mouse cursor.\n"
        "When the user says 'here', 'this spot', 'right there', use cursor-based tools.\n\n"
        "TOOLS:\n"
        "- navigate(url)\n"
        "- scroll(delta_y, delta_x=0)  # wheel scroll; on maps wheel often acts like zoom\n"
        "- pan(direction, amount=300)\n"
        "- click(x,y), drag(x1,y1,x2,y2)\n"
        "- screenshot_base64(full_page=False)\n"
        "- click_cursor(user_id, session_id)\n"
        "- scroll_cursor(user_id, session_id, delta_y, delta_x=0)\n"
        "- drag_cursor(user_id, session_id, dx, dy)\n\n"
        "RULES:\n"
        "1) If user asks to open a site/page: navigate(url).\n"
        "2) If user says 'scroll up/down': use scroll(delta_y=...)\n"
        "3) If user says 'zoom in/out here' or 'zoom this area' or 'right there': "
        "use scroll_cursor(user_id, session_id, delta_y=...) where delta_y<0 means wheel up.\n"
        "4) If user says 'click here/right there': use click_cursor(user_id, session_id).\n"
        "5) If user says 'drag/pan from here': use drag_cursor(user_id, session_id, dx, dy).\n"
        "6) Keep confirmations short.\n"
    ),
    tools=[navigate, screenshot_base64, click, drag, scroll, pan, click_cursor, scroll_cursor, drag_cursor],
)