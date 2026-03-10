from app.live.trace import (
    make_audio_gate_message,
    build_trace_event,
    format_trace_event,
    make_client_trace_message,
    make_cursor_ack,
    make_session_meta,
    make_trace_message,
    parse_trace_payload,
)


def test_trace_event_round_trip_message_shape() -> None:
    payload = build_trace_event(
        request_id="req-1",
        session_id="sess-1",
        source="server",
        event="tool_called",
        status="started",
        summary="navigate https://example.com",
        agent_name="browser_agent",
        tool_name="navigate",
        duration_ms=12,
        cursor={"x": 1, "y": 2},
        metadata={"display_id": 7},
        ts=10.0,
        event_id="evt-1",
    )
    message = make_trace_message(payload)

    assert message["type"] == "trace_event"
    assert message["event_id"] == "evt-1"
    assert message["request_id"] == "req-1"
    assert message["cursor"] == {"x": 1, "y": 2}
    assert message["metadata"] == {"display_id": 7}

    client_message = make_client_trace_message(payload)
    parsed = parse_trace_payload(
        client_message,
        expected_type="client_trace",
        expected_source="server",
        expected_session_id="sess-1",
    )

    assert client_message["type"] == "client_trace"
    assert parsed is not None
    assert parsed["event_id"] == "evt-1"

    line = format_trace_event(payload)
    assert line == (
        "[trace][server] event=tool_called status=started rid=req-1 "
        "agent=browser_agent tool=navigate summary=navigate https://example.com"
    )


def test_session_meta_and_cursor_ack_shape() -> None:
    meta = make_session_meta(session_id="sess-1", service="svc", revision="rev-1", commit="abc123")
    ack = make_cursor_ack(session_id="sess-1", request_id="cursor:3", x=9, y=8, ts=4.0)
    gate = make_audio_gate_message(session_id="sess-1", state="closed", reason="transfer_to_agent")

    assert meta == {
        "type": "session_meta",
        "session_id": "sess-1",
        "service": "svc",
        "revision": "rev-1",
        "commit": "abc123",
    }
    assert ack["type"] == "cursor_ack"
    assert ack["cursor"] == {"x": 9, "y": 8}
    assert gate == {
        "type": "audio_gate",
        "session_id": "sess-1",
        "state": "closed",
        "reason": "transfer_to_agent",
    }
