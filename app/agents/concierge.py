from google.adk.agents import Agent
from .browser_agent import browser_agent
from .echo_dedupe import echo_dedupe_before_tool_callback
from .handoff_guard import transfer_audio_gate_before_tool_callback

MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"

root_agent = Agent(
    name="concierge",
    model=MODEL,
    description="A voice-first concierge that chats with the user and delegates browser tasks.",
    instruction=(
        "You are the default voice-first concierge and overall conversation owner. Keep responses short and conversational. "
        "If the user asks to browse, open a website, click/zoom/scroll somewhere, or refers to 'here/right there', delegate to browser_agent. "
        "If the current conversation is no longer about browser control, handle it yourself. "
        "After opening, tell the user what you opened."
    ),
    before_tool_callback=[
        echo_dedupe_before_tool_callback,
        transfer_audio_gate_before_tool_callback,
    ],
    sub_agents=[browser_agent],
)
