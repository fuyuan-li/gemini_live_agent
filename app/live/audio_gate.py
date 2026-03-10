from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from .resettable_queue import ResettableLiveRequestQueue


@dataclass
class SessionAudioGate:
    queue: ResettableLiveRequestQueue
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    allow_audio_upload: bool = True
    handoff_pending: bool = False
    target_agent: Optional[str] = None
    speech_active: bool = False
    silence_started_at: Optional[float] = None
    reopen_task: Optional[asyncio.Task[None]] = None


_gates: dict[tuple[str, str], SessionAudioGate] = {}


def register_audio_gate(user_id: str, session_id: str, gate: SessionAudioGate) -> None:
    _gates[(str(user_id), str(session_id))] = gate


def get_audio_gate(user_id: str, session_id: str) -> Optional[SessionAudioGate]:
    return _gates.get((str(user_id), str(session_id)))


def unregister_audio_gate(user_id: str, session_id: str) -> Optional[SessionAudioGate]:
    gate = _gates.pop((str(user_id), str(session_id)), None)
    if gate is None:
        return None
    task = gate.reopen_task
    if task is not None and not task.done():
        task.cancel()
    gate.reopen_task = None
    return gate
