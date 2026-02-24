from google.adk.agents import Agent
from .browser_agent import browser_agent

MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"

root_agent = Agent(
    name="concierge",
    model=MODEL,
    description="A voice-first concierge that chats with the user and can open web pages via a sub-agent.",
    instruction=(
        "You are a voice-first concierge. Keep responses short and conversational. "
        "If the user asks to open a website or go to a page, delegate to browser_agent. "
        "After opening, tell the user what you opened."
    ),
    sub_agents=[browser_agent],
)