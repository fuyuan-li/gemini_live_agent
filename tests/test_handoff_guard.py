import asyncio
import json

from google.genai import types

from app.callbacks.handoff_guard import clear_transfer_audio_gate
from app.callbacks.handoff_guard import reopen_transfer_audio_gate
from app.callbacks.handoff_guard import transfer_audio_gate_before_tool_callback
from app.live.audio_gate import SessionAudioGate
from app.live.audio_gate import register_audio_gate
from app.live.audio_gate import unregister_audio_gate
from app.live.resettable_queue import ResettableLiveRequestQueue
from app.runtime.session_bridge import register_bridge
from app.runtime.session_bridge import unregister_bridge


class _FakeTool:
    name = "transfer_to_agent"


class _FakeOtherTool:
    name = "search"


class _FakeSession:
    id = "session-1"


class _FakeToolContext:
    def __init__(self) -> None:
        self.user_id = "user-1"
        self.session = _FakeSession()


class _FakeWebSocket:
    def __init__(self) -> None:
        self.text_frames: list[str] = []

    async def send_text(self, payload: str) -> None:
        self.text_frames.append(payload)

    async def send_bytes(self, payload: bytes) -> None:
        raise AssertionError("unexpected binary frame")


def test_transfer_guard_closes_audio_gate_and_notifies_client() -> None:
    async def scenario() -> None:
        queue = ResettableLiveRequestQueue()
        queue.send_realtime(types.Blob(mime_type="audio/pcm;rate=16000", data=b"123"))
        gate = SessionAudioGate(queue=queue)
        ws = _FakeWebSocket()
        bridge = await register_bridge("user-1", "session-1", ws)
        register_audio_gate("user-1", "session-1", gate)
        try:
            result = await transfer_audio_gate_before_tool_callback(
                _FakeTool(),
                {"agent_name": "concierge"},
                _FakeToolContext(),
            )

            assert result is None
            assert gate.allow_audio_upload is False
            assert gate.handoff_pending is True
            assert gate.target_agent == "concierge"
            assert gate.reopen_task is not None
            assert len(ws.text_frames) == 1
            assert json.loads(ws.text_frames[0])["type"] == "audio_gate"
            assert queue._queue.empty()
            await clear_transfer_audio_gate(user_id="user-1", session_id="session-1")
        finally:
            await unregister_bridge("user-1", "session-1", bridge)
            unregister_audio_gate("user-1", "session-1")

    asyncio.run(scenario())


def test_transfer_guard_ignores_non_transfer_tools() -> None:
    async def scenario() -> None:
        queue = ResettableLiveRequestQueue()
        gate = SessionAudioGate(queue=queue)
        register_audio_gate("user-1", "session-1", gate)
        try:
            result = await transfer_audio_gate_before_tool_callback(
                _FakeOtherTool(),
                {},
                _FakeToolContext(),
            )

            assert result is None
            assert gate.allow_audio_upload is True
            assert gate.handoff_pending is False
            assert gate.reopen_task is None
        finally:
            unregister_audio_gate("user-1", "session-1")

    asyncio.run(scenario())


def test_reopen_transfer_audio_gate_notifies_client() -> None:
    async def scenario() -> None:
        queue = ResettableLiveRequestQueue()
        gate = SessionAudioGate(queue=queue, allow_audio_upload=False, handoff_pending=True, target_agent="concierge")
        ws = _FakeWebSocket()
        bridge = await register_bridge("user-1", "session-1", ws)
        register_audio_gate("user-1", "session-1", gate)
        try:
            reopened = await reopen_transfer_audio_gate(
                user_id="user-1",
                session_id="session-1",
                reason="transfer_to_agent",
            )

            assert reopened is True
            assert gate.allow_audio_upload is True
            assert gate.handoff_pending is False
            assert gate.target_agent is None
            assert json.loads(ws.text_frames[0]) == {
                "type": "audio_gate",
                "session_id": "session-1",
                "state": "open",
                "reason": "transfer_to_agent",
            }
        finally:
            await unregister_bridge("user-1", "session-1", bridge)
            unregister_audio_gate("user-1", "session-1")

    asyncio.run(scenario())
