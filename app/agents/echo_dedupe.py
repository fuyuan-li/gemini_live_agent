from __future__ import annotations

import re
from typing import Any, Optional

from app.live.trace import build_trace_event, log_trace_event


LATEST_MODEL_OUTPUT_KEY = "latest_model_output"
LATEST_USER_INPUT_KEY = "latest_user_input"
_TRAILING_PUNCT_RE = re.compile(r"[\s\.,!?;:'\"`]+$")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_echo_text(value: Optional[str]) -> str:
    if not value:
        return ""
    text = _WHITESPACE_RE.sub(" ", str(value).strip().lower())
    return _TRAILING_PUNCT_RE.sub("", text)


def is_echo_replay(latest_model_output: Optional[str], latest_user_input: Optional[str]) -> bool:
    model_text = normalize_echo_text(latest_model_output)
    user_text = normalize_echo_text(latest_user_input)
    if not model_text or not user_text:
        return False
    return model_text == user_text


async def echo_dedupe_before_tool_callback(tool, args: dict[str, Any], tool_context) -> Optional[dict[str, Any]]:
    latest_model_output = tool_context.state.get(LATEST_MODEL_OUTPUT_KEY)
    latest_user_input = tool_context.state.get(LATEST_USER_INPUT_KEY)
    if not is_echo_replay(latest_model_output, latest_user_input):
        return None

    event = build_trace_event(
        request_id=tool_context.invocation_id,
        session_id=tool_context.session.id,
        source="server",
        event="tool_deduped",
        status="ok",
        summary=f"{tool.name} reason=echo_deduped",
        agent_name=tool_context.agent_name,
        tool_name=tool.name,
        metadata={
            "reason": "echo_deduped",
            "latest_model_output": str(latest_model_output or ""),
            "latest_user_input": str(latest_user_input or ""),
        },
    )
    log_trace_event(event)
    print(
        "[tool_deduped] "
        f"user={tool_context.user_id} session={tool_context.session.id} "
        f"agent={tool_context.agent_name} tool={tool.name} reason=echo_deduped "
        f"latest_model_output={latest_model_output!r} latest_user_input={latest_user_input!r}"
    )
    return {
        "ok": True,
        "ignored": True,
        "reason": "echo_deduped",
    }
