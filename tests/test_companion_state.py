from client.companion_state import CompanionState
from client.cursor.types import CursorSample, NormalizedSample


def test_companion_state_tracks_meta_cursors_and_events() -> None:
    state = CompanionState(session_id="sess-1")

    state.update_local_capture(
        cursor=CursorSample(x=10, y=20, ts=1.0, source="hand", confidence=0.9),
        fingertip=NormalizedSample(x=0.4, y=0.6, ts=1.0, confidence=0.9),
    )
    state.handle_server_message(
        {
            "type": "session_meta",
            "session_id": "sess-1",
            "service": "svc",
            "revision": "rev-2",
            "commit": "abc",
        }
    )
    state.handle_server_message(
        {
            "type": "cursor_ack",
            "session_id": "sess-1",
            "request_id": "cursor:7",
            "cursor": {"x": 11, "y": 21},
            "ts": 2.0,
        }
    )
    state.record_local_event(
        request_id="req-1",
        event="audio_stream_started",
        status="ok",
        summary="started",
        agent_name="concierge",
    )
    state.handle_server_message(
        {
            "type": "trace_event",
            "event_id": "evt-1",
            "request_id": "req-1",
            "session_id": "sess-1",
            "source": "server",
            "event": "tool_called",
            "status": "started",
            "summary": "navigate",
            "tool_name": "navigate",
            "agent_name": "browser_agent",
            "ts": 3.0,
        }
    )

    snapshot = state.snapshot()

    assert snapshot.session_meta is not None
    assert snapshot.session_meta.revision == "rev-2"
    assert snapshot.local_cursor is not None
    assert snapshot.local_cursor.x == 10
    assert snapshot.server_cursor is not None
    assert snapshot.server_cursor.y == 21
    assert snapshot.current_agent == "browser_agent"
    assert snapshot.current_tool == "navigate"
    assert len(snapshot.latest_events) == 2


def test_companion_state_clears_stale_tool_on_agent_level_event() -> None:
    state = CompanionState(session_id="sess-1")
    state.handle_server_message(
        {
            "type": "trace_event",
            "event_id": "evt-1",
            "request_id": "req-1",
            "session_id": "sess-1",
            "source": "server",
            "event": "tool_called",
            "status": "started",
            "summary": "click_here",
            "tool_name": "click_here",
            "agent_name": "browser_agent",
            "ts": 1.0,
        }
    )
    state.handle_server_message(
        {
            "type": "trace_event",
            "event_id": "evt-2",
            "request_id": "req-2",
            "session_id": "sess-1",
            "source": "server",
            "event": "agent_spoke",
            "status": "ok",
            "summary": "Back to concierge.",
            "agent_name": "concierge",
            "ts": 2.0,
        }
    )

    snapshot = state.snapshot()

    assert snapshot.current_agent == "concierge"
    assert snapshot.current_tool is None


def test_companion_state_notifies_local_trace_listener_for_local_events() -> None:
    state = CompanionState(session_id="sess-1")
    seen: list[dict[str, object]] = []
    state.set_local_trace_listener(lambda payload: seen.append(payload))

    state.record_local_event(
        request_id="req-9",
        event="session_connected",
        status="ok",
        summary="connected",
        agent_name="concierge",
    )

    assert len(seen) == 1
    assert seen[0]["source"] == "client"
    assert seen[0]["event"] == "session_connected"
    assert seen[0]["agent_name"] == "concierge"
