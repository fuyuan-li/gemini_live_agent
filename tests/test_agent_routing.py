from pathlib import Path


def test_concierge_routes_to_browser_agent() -> None:
    p = Path("app/agents/concierge.py")
    text = p.read_text(encoding="utf-8")

    assert "from .browser_agent import browser_agent" in text
    assert "sub_agents=[browser_agent]" in text
