import asyncio

from app.agents.browser_agent import browser_agent
from app.agents.concierge import root_agent
from app.agents.echo_dedupe import (
    LATEST_MODEL_OUTPUT_KEY,
    LATEST_USER_INPUT_KEY,
    echo_dedupe_before_tool_callback,
    is_echo_replay,
)
from app.agents.handoff_guard import transfer_audio_gate_before_tool_callback


class _FakeSession:
    id = "session-1"


class _FakeToolContext:
    def __init__(self, *, latest_model_output: str, latest_user_input: str) -> None:
        self.state = {
            LATEST_MODEL_OUTPUT_KEY: latest_model_output,
            LATEST_USER_INPUT_KEY: latest_user_input,
        }
        self.invocation_id = "inv-1"
        self.session = _FakeSession()
        self.user_id = "user-1"
        self.agent_name = "browser_agent"


class _FakeTool:
    name = "remote_click_here"


def test_is_echo_replay_normalizes_case_spacing_and_punctuation() -> None:
    assert is_echo_replay(
        "OK, I've scrolled down.",
        "  ok, i've scrolled down   ",
    )


def test_echo_dedupe_before_tool_callback_short_circuits_matching_replay() -> None:
    result = asyncio.run(
        echo_dedupe_before_tool_callback(
            _FakeTool(),
            {},
            _FakeToolContext(
                latest_model_output="OK, I've scrolled down.",
                latest_user_input="ok, i've scrolled down",
            ),
        )
    )

    assert result == {
        "ok": True,
        "ignored": True,
        "reason": "echo_deduped",
    }


def test_echo_dedupe_before_tool_callback_allows_non_matching_input() -> None:
    result = asyncio.run(
        echo_dedupe_before_tool_callback(
            _FakeTool(),
            {},
            _FakeToolContext(
                latest_model_output="OK, I've scrolled down.",
                latest_user_input="click here",
            ),
        )
    )

    assert result is None


def test_agents_share_same_echo_dedupe_callback() -> None:
    assert browser_agent.before_tool_callback == [
        echo_dedupe_before_tool_callback,
        transfer_audio_gate_before_tool_callback,
    ]
    assert root_agent.before_tool_callback == [
        echo_dedupe_before_tool_callback,
        transfer_audio_gate_before_tool_callback,
    ]
