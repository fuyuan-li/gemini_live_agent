from __future__ import annotations

import base64
from uuid import uuid4

from google.adk.tools.tool_context import ToolContext
from google.genai import types

from app.live.audio_gate import get_audio_gate
from app.runtime.realtime_pointer import get_cursor
from app.runtime.session_bridge import call_local_tool


def _get_uid_sid(tc: ToolContext) -> tuple[str, str]:
    inv = getattr(tc, "_invocation_context", None)
    if inv is None:
        return "unknown_user", "unknown_session"
    uid = getattr(inv, "user_id", None) or "unknown_user"
    sess = getattr(inv, "session", None)
    sid = getattr(sess, "id", None) if sess is not None else "unknown_session"
    return str(uid), str(sid)


async def remote_screenshot(tool_context: ToolContext) -> dict:
    """Capture the user's screen, annotated with the cursor position, and inject it into the Gemini context."""
    user_id, session_id = _get_uid_sid(tool_context)

    cursor = await get_cursor(user_id, session_id)
    args: dict = {}
    if cursor:
        args = {"cursor_x": cursor["x"], "cursor_y": cursor["y"]}

    result = await call_local_tool(
        user_id=user_id,
        session_id=session_id,
        tool="screenshot",
        args=args,
        request_id=str(uuid4()),
        agent_name="concierge",
    )

    gate = get_audio_gate(user_id, session_id)
    if gate and result.get("data"):
        raw = base64.b64decode(result["data"])
        gate.queue.send_realtime(types.Blob(mime_type="image/jpeg", data=raw))

    response: dict = {
        "status": "screenshot captured",
        "width": result.get("width"),
        "height": result.get("height"),
    }
    if cursor:
        response["cursor_x"] = cursor["x"]
        response["cursor_y"] = cursor["y"]
        response["note"] = "The screenshot has been annotated with a cursor marker at the above coordinates. Describe what is at or near the cursor, not the whole screen."
    return response
