from google.adk.agents import Agent
from .browser_agent import browser_agent

MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"

root_agent = Agent(
    name="concierge",
    model=MODEL,
    description="A voice-first concierge that chats with the user and delegates browser tasks.",
    instruction=(
        "You are a voice-first concierge. Keep responses short and conversational. "
        "If the user asks to browse, open a website, click/zoom/scroll somewhere, or refers to 'here/right there', delegate to browser_agent. "
        "After opening, tell the user what you opened."
    ),
    sub_agents=[browser_agent],
)
