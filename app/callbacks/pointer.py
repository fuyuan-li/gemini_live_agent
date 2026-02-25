from __future__ import annotations

from typing import Any, Dict, Optional

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

from app.state.realtime_pointer import get_cursor


def _get_uid_sid(tc: ToolContext) -> tuple[str, str]:
    """
    Robustly extract (user_id, session_id) from ToolContext across ADK versions.
    """
    inv = getattr(tc, "_invocation_context", None)
    if inv is None:
        return "unknown_user", "unknown_session"

    uid = getattr(inv, "user_id", None) or "unknown_user"
    sess = getattr(inv, "session", None)
    sid = getattr(sess, "id", None) if sess is not None else "unknown_session"
    return str(uid), str(sid)


async def before_tool_inject_cursor(
    tool: BaseTool,
    args: Dict[str, Any],
    tool_context: ToolContext,
) -> Optional[Dict]:
    """
    1) Print:
       - uid/sid from invocation_context
       - tool_context.state cursor (delta-aware view)
       - invocation_context.session.state cursor (snapshot inside invocation)
       - realtime store cursor (what ws is updating)
    2) Inject realtime cursor into tool_context.state['cursor'] so HERE tools can read it.
    """
    uid, sid = _get_uid_sid(tool_context)

    # ToolContext delta-aware view
    tc_cursor = tool_context.state.get("cursor")

    # Invocation snapshot view (what this invocation started with)
    inv = getattr(tool_context, "_invocation_context", None)
    inv_cursor = None
    if inv is not None and getattr(inv, "session", None) is not None:
        inv_cursor = (inv.session.state or {}).get("cursor")

    # Realtime latest (from ws thread)
    rt_cursor = await get_cursor(uid, sid)

    print(
        f"[before_tool] tool={getattr(tool, 'name', type(tool).__name__)} "
        f"uid={uid} sid={sid} "
        f"tc.cursor={tc_cursor} inv.cursor={inv_cursor} rt.cursor={rt_cursor}"
    )

    # Inject
    if rt_cursor is not None:
        tool_context.state["cursor"] = {
            "x": int(rt_cursor["x"]),
            "y": int(rt_cursor["y"]),
            "ts": float(rt_cursor["ts"]),
        }

    return None