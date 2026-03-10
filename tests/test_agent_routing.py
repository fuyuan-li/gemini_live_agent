from pathlib import Path


def test_concierge_routes_to_browser_agent() -> None:
    p = Path("app/agents/concierge.py")
    text = p.read_text(encoding="utf-8")

    assert "from .browser_agent import browser_agent" in text
    assert "sub_agents=[browser_agent]" in text
    assert "default voice-first concierge and overall conversation owner" in text


def test_browser_agent_instruction_mentions_transfer_back_to_concierge() -> None:
    text = Path("app/agents/browser_agent.py").read_text(encoding="utf-8")

    assert "transfer_to_agent(agent_name='concierge')" in text
    assert "If the request is not browser control, transfer to concierge." in text
    assert "Examples that should transfer to concierge" in text
