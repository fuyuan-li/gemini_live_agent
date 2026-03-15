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
        "You are the voice-first concierge. Always respond in English. Keep responses to 1-2 sentences.\n\n"
        "DELEGATE TO browser_agent immediately (no summary, no confirmation first) for:\n"
        "- Any browser/navigation/click/scroll/zoom/drag task.\n"
        "- Searching within a website ('find X on YouTube', 'search X on Amazon', 'show X near me on maps').\n"
        "- Anything the user points at ('here', 'this', 'right there').\n"
        "- 'What is this?' or screen questions while browsing — browser_agent has remote_screenshot.\n"
        "- 'I need to buy X' → delegate to browser_agent to navigate Amazon.\n\n"
        "USE search_agent (do not open a browser) for:\n"
        "- Standalone factual questions: 'what's the weather', 'who is X', 'what time is it in X'.\n"
        "- These can happen mid-session (e.g. user asks about weather after browsing maps).\n\n"
        "HANDLE YOURSELF:\n"
        "- Pure conversation, jokes, opinions, greetings.\n\n"
        "Never ask clarifying questions before delegating. Transfer with the full user request intact."
    ),
    before_tool_callback=[
        echo_dedupe_before_tool_callback,
        transfer_audio_gate_before_tool_callback,
    ],
    tools=[AgentTool(agent=search_agent, skip_summarization=True), remote_screenshot],
    sub_agents=[browser_agent],
)
