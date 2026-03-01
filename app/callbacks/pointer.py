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
    print(f"[before_tool] tool={tool.name} args={args}")
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

    err = cursor_in_screen(tool, args, tool_context)  # optionally block if cursor looks off-screen
    if err is not None:
        return err
    
    return None


HERE_TOOLS = {"click_here", "scroll_here", "drag_here"}

def cursor_in_screen(
    tool: BaseTool,
    args: Dict[str, Any],
    tool_context: ToolContext,
) -> Optional[Dict[str, Any]]:
    # 只对 HERE tools 做 cursor 检查
    if tool.name in HERE_TOOLS:
        cur = tool_context.state.get("cursor")
        if not cur:
            return {"error": "I can't find your pointer position yet. Move your hand to the target area and try again."}

        try:
            x = int(cur.get("x"))
            y = int(cur.get("y"))
        except Exception:
            return {"error": "Cursor state is malformed; please try again."}

        # if x < 0 or y < 0:
        #     return {
        #         "error": "Your cursor looks off-screen. Please move it onto the target area (e.g., the map) and say it again."
        #     }

    # tool-specific arg sanity：按你的 tools 实际参数名来
    if tool.name in {"scroll_here", "scroll"}:
        try:
            float(args.get("delta_y", 0))
            float(args.get("delta_x", 0))
        except Exception:
            return {"error": "Scroll arguments are invalid; please try again."}

    if tool.name == "drag_here":
        try:
            float(args.get("dx", 0))
            float(args.get("dy", 0))
        except Exception:
            return {"error": "Drag arguments are invalid; please try again."}

    return None
