from __future__ import annotations

import difflib
import re
from typing import Any, Optional

from google.genai import types

from app.live.trace import build_trace_event, log_trace_event


LATEST_MODEL_OUTPUT_KEY = "latest_model_output"
LATEST_USER_INPUT_KEY = "latest_user_input"
_NON_WORD_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")
_FUZZY_REPLAY_MIN_CHARS = 24
_FUZZY_REPLAY_MIN_RATIO = 0.92


def normalize_echo_text(value: Optional[str]) -> str:
    if not value:
        return ""
    text = _NON_WORD_RE.sub(" ", str(value).strip().lower())
    return _WHITESPACE_RE.sub(" ", text).strip()


def is_echo_replay(latest_model_output: Optional[str], latest_user_input: Optional[str]) -> bool:
    model_text = normalize_echo_text(latest_model_output)
    user_text = normalize_echo_text(latest_user_input)
    if not model_text or not user_text:
        return False
    if model_text == user_text:
        return True

    longest_len = max(len(model_text), len(user_text))
    shortest_len = min(len(model_text), len(user_text))
    if shortest_len < _FUZZY_REPLAY_MIN_CHARS:
        return False

    ratio = difflib.SequenceMatcher(None, model_text, user_text).ratio()
    if ratio < _FUZZY_REPLAY_MIN_RATIO:
        return False

    return shortest_len / longest_len >= 0.75


def extract_text_from_content(content: Optional[types.Content]) -> str:
    if content is None or not content.parts:
        return ""
    parts: list[str] = []
    for part in content.parts:
        text = getattr(part, "text", None)
        if text:
            parts.append(str(text))
    return " ".join(parts).strip()


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


async def echo_dedupe_before_agent_callback(callback_context) -> Optional[types.Content]:
    latest_model_output = callback_context.state.get(LATEST_MODEL_OUTPUT_KEY)
    latest_user_input = extract_text_from_content(getattr(callback_context, "user_content", None))
    if not latest_user_input:
        latest_user_input = str(callback_context.state.get(LATEST_USER_INPUT_KEY) or "")
    if not is_echo_replay(latest_model_output, latest_user_input):
        return None

    event = build_trace_event(
        request_id=callback_context.invocation_id,
        session_id=callback_context.session.id,
        source="server",
        event="agent_deduped",
        status="ok",
        summary="before_agent reason=echo_deduped",
        agent_name=callback_context.agent_name,
        metadata={
            "reason": "echo_deduped",
            "latest_model_output": str(latest_model_output or ""),
            "latest_user_input": str(latest_user_input or ""),
        },
    )
    log_trace_event(event)
    print(
        "[agent_deduped] "
        f"user={callback_context.user_id} session={callback_context.session.id} "
        f"agent={callback_context.agent_name} reason=echo_deduped "
        f"latest_model_output={latest_model_output!r} latest_user_input={latest_user_input!r}"
    )
    return types.Content(parts=[])
