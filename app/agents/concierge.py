from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool
from .browser_agent import browser_agent
from .search_agent import search_agent
from app.callbacks.echo_dedupe import echo_dedupe_before_tool_callback
from app.callbacks.handoff_guard import transfer_audio_gate_before_tool_callback
from app.tools.remote_vision import remote_screenshot

MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"

root_agent = Agent(
    name="concierge",
    model=MODEL,
    description="A voice-first concierge that chats with the user and delegates browser tasks.",
    instruction=(
        "You are the default voice-first concierge and overall conversation owner. Always respond in English only, regardless of what language you think you heard. Keep responses short and conversational. "
        "If the user asks to browse, open a website, click/zoom/scroll somewhere, or refers to 'here/right there', delegate to browser_agent. "
        "If the user asks a factual question, wants to search for something, or asks about current events/news, call the search_agent tool and read the result back to the user. "
        "If the current conversation is no longer about browser control or search, handle it yourself. "
        "After opening, tell the user what you opened. "
        "When the user asks about something they can see on screen ('what is this?', 'what does this say?', 'what am I looking at?', 'can you see this?'), call remote_screenshot to capture their screen. The screenshot will appear in your context — describe what you see and answer the question. Use search_agent afterwards if you need more information about what you see."
    ),
    before_tool_callback=[
        echo_dedupe_before_tool_callback,
        transfer_audio_gate_before_tool_callback,
    ],
    tools=[AgentTool(agent=search_agent, skip_summarization=True), remote_screenshot],
    sub_agents=[browser_agent],
)
