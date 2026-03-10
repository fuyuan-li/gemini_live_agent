from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

from app.live.audio_gate import get_audio_gate
from app.live.trace import make_audio_gate_message
from app.runtime.session_bridge import get_bridge


TRANSFER_AUDIO_GATE_REOPEN_DELAY_S = float(
    os.getenv("TRANSFER_AUDIO_GATE_REOPEN_DELAY_S", "1.25")
)
logger = logging.getLogger("app.agents.handoff_guard")


async def reopen_transfer_audio_gate(
    *,
    user_id: str,
    session_id: str,
    reason: str,
) -> bool:
    gate = get_audio_gate(user_id, session_id)
    if gate is None:
        return False

    async with gate.lock:
        current_task = asyncio.current_task()
        if gate.reopen_task is current_task:
            gate.reopen_task = None
        gate.allow_audio_upload = True
        gate.handoff_pending = False
        gate.target_agent = None
        gate.speech_active = False
        gate.silence_started_at = None

    bridge = await get_bridge(user_id, session_id)
    if bridge is not None:
        await bridge.send_json(
            make_audio_gate_message(
                session_id=session_id,
                state="open",
                reason=reason,
            )
        )
    logger.info(
        "[transfer.guard] reopened audio gate user=%s session=%s reason=%s",
        user_id,
        session_id,
        reason,
    )
    return True


async def clear_transfer_audio_gate(
    *,
    user_id: str,
    session_id: str,
) -> bool:
    gate = get_audio_gate(user_id, session_id)
    if gate is None:
        return False

    async with gate.lock:
        task = gate.reopen_task
        gate.reopen_task = None
        gate.allow_audio_upload = True
        gate.handoff_pending = False
        gate.target_agent = None
        gate.speech_active = False
        gate.silence_started_at = None

    if task is not None and not task.done():
        task.cancel()
    return True


async def transfer_audio_gate_before_tool_callback(
    tool,
    args: dict[str, Any],
    tool_context,
) -> Optional[dict]:
    if getattr(tool, "name", "") != "transfer_to_agent":
        return None

    user_id = str(getattr(tool_context, "user_id", "") or "")
    session = getattr(tool_context, "session", None)
    session_id = str(getattr(session, "id", "") or "")
    if not user_id or not session_id:
        return None

    gate = get_audio_gate(user_id, session_id)
    if gate is None:
        return None

    target_agent = str(args.get("agent_name", "") or "").strip() or None

    async with gate.lock:
        task = gate.reopen_task
        gate.reopen_task = None
        was_speech_active = gate.speech_active
        gate.allow_audio_upload = False
        gate.handoff_pending = True
        gate.target_agent = target_agent
        gate.speech_active = False
        gate.silence_started_at = None
        dropped = gate.queue.drop_realtime_backlog()
        if was_speech_active or dropped:
            gate.queue.send_activity_end()
        gate.reopen_task = asyncio.create_task(
            _reopen_after_transfer_delay(user_id=user_id, session_id=session_id)
        )

    if task is not None and not task.done():
        task.cancel()

    bridge = await get_bridge(user_id, session_id)
    if bridge is not None:
        await bridge.send_json(
            make_audio_gate_message(
                session_id=session_id,
                state="closed",
                reason="transfer_to_agent",
            )
        )

    logger.info(
        "[transfer.guard] closed audio gate user=%s session=%s target=%s dropped=%s",
        user_id,
        session_id,
        target_agent,
        dropped,
    )
    return None


async def _reopen_after_transfer_delay(*, user_id: str, session_id: str) -> None:
    try:
        await asyncio.sleep(TRANSFER_AUDIO_GATE_REOPEN_DELAY_S)
        await reopen_transfer_audio_gate(
            user_id=user_id,
            session_id=session_id,
            reason="transfer_to_agent",
        )
    except asyncio.CancelledError:
        raise
