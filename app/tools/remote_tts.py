from __future__ import annotations

from uuid import uuid4

from google.adk.tools.tool_context import ToolContext

from app.runtime.session_bridge import call_local_tool


def _get_uid_sid(tc: ToolContext) -> tuple[str, str]:
    inv = getattr(tc, "_invocation_context", None)
    if inv is None:
        return "unknown_user", "unknown_session"
    uid = getattr(inv, "user_id", None) or "unknown_user"
    sess = getattr(inv, "session", None)
    sid = getattr(sess, "id", None) if sess is not None else "unknown_session"
    return str(uid), str(sid)


async def speak_text(text: str, tool_context: ToolContext) -> dict:
    """Speak text aloud on the user's local machine."""
    user_id, session_id = _get_uid_sid(tool_context)
    result = await call_local_tool(
        user_id=user_id,
        session_id=session_id,
        tool="tts",
        args={"text": text},
        request_id=str(uuid4()),
        agent_name="browser_agent",
    )
    return result
