from __future__ import annotations

from time import time
from typing import Any, Dict
from uuid import uuid4

from google.adk.tools.tool_context import ToolContext

from app.runtime.session_bridge import call_local_tool, emit_server_trace


def _get_uid_sid(tc: ToolContext) -> tuple[str, str]:
    inv = getattr(tc, "_invocation_context", None)
    if inv is None:
        return "unknown_user", "unknown_session"

    uid = getattr(inv, "user_id", None) or "unknown_user"
    sess = getattr(inv, "session", None)
    sid = getattr(sess, "id", None) if sess is not None else "unknown_session"
    return str(uid), str(sid)


async def _call(tool_context: ToolContext, tool_name: str, args: Dict[str, Any]) -> dict:
    user_id, session_id = _get_uid_sid(tool_context)
    request_id = str(uuid4())
    t0 = time()
    await emit_server_trace(
        user_id=user_id,
        session_id=session_id,
        request_id=request_id,
        event="agent_started",
        status="started",
        summary=f"browser_agent handling {tool_name}",
        agent_name="browser_agent",
        tool_name=tool_name,
    )
    try:
        result = await call_local_tool(
            user_id=user_id,
            session_id=session_id,
            tool=tool_name,
            args=args,
            request_id=request_id,
            agent_name="browser_agent",
        )
    except Exception as exc:
        await emit_server_trace(
            user_id=user_id,
            session_id=session_id,
            request_id=request_id,
            event="agent_finished",
            status="error",
            summary=str(exc),
            agent_name="browser_agent",
            tool_name=tool_name,
            duration_ms=int((time() - t0) * 1000),
        )
        raise
    await emit_server_trace(
        user_id=user_id,
        session_id=session_id,
        request_id=request_id,
        event="agent_finished",
        status="ok",
        summary=f"browser_agent completed {tool_name}",
        agent_name="browser_agent",
        tool_name=tool_name,
        duration_ms=int((time() - t0) * 1000),
    )
    return result


async def remote_navigate(tool_context: ToolContext, url: str) -> dict:
    return await _call(tool_context, "navigate", {"url": url})


async def remote_pan(tool_context: ToolContext, direction: str, amount: int = 300) -> dict:
    return await _call(tool_context, "pan", {"direction": direction, "amount": int(amount)})


async def remote_click_here(tool_context: ToolContext) -> dict:
    return await _call(tool_context, "click_here", {})


async def remote_scroll_here(tool_context: ToolContext, delta_y: int, delta_x: int = 0) -> dict:
    return await _call(
        tool_context,
        "scroll_here",
        {"delta_y": int(delta_y), "delta_x": int(delta_x)},
    )


async def remote_drag_here(tool_context: ToolContext, dx: int, dy: int, steps: int = 30) -> dict:
    return await _call(
        tool_context,
        "drag_here",
        {"dx": int(dx), "dy": int(dy), "steps": int(steps)},
    )


async def remote_play_pause(tool_context: ToolContext) -> dict:
    return await _call(tool_context, "play_pause", {})


async def remote_go_back(tool_context: ToolContext) -> dict:
    return await _call(tool_context, "go_back", {})
