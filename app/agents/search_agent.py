from google.adk.agents import Agent
from google.adk.tools import google_search
from app.callbacks.echo_dedupe import echo_dedupe_before_tool_callback
from app.callbacks.handoff_guard import transfer_audio_gate_before_tool_callback

MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"

search_agent = Agent(
    name="search_agent",
    model=MODEL,
    description="Answers factual questions and looks up current information using Google Search.",
    instruction=(
        "You answer questions by searching the web with Google Search.\n\n"
        "Scope:\n"
        "- Handle any question that benefits from a live web search: facts, news, prices, how-to, definitions, etc.\n"
        "- Keep answers concise and conversational — this is a voice interface.\n"
        "- When you have answered the user's question, or if the request is outside your scope (browser control, chit-chat), "
        "transfer back to concierge without explanatory text: transfer_to_agent(agent_name='concierge').\n\n"
        "RULES:\n"
        "1) Always use google_search to look up current or factual information before answering.\n"
        "2) Summarize results briefly — do not read out long lists.\n"
        "3) When done or out of scope, silently transfer_to_agent(agent_name='concierge').\n"
    ),
    before_tool_callback=[
        echo_dedupe_before_tool_callback,
        transfer_audio_gate_before_tool_callback,
    ],
    tools=[google_search],
)
