from google.adk.agents import Agent
from google.adk.tools import google_search

MODEL = "gemini-2.5-flash"

search_agent = Agent(
    name="search_agent",
    model=MODEL,
    description="Answers factual questions and looks up current information using Google Search.",
    instruction=(
        "You answer questions by searching the web with Google Search.\n"
        "Always use google_search before answering.\n"
        "Return a concise, factual answer in plain text — 1-3 sentences max.\n"
        "Do not include lists, markdown, or headers. Plain prose only."
    ),
    tools=[google_search],
)
