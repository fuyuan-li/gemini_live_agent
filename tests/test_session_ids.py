from client.session_ids import build_ws_session_url, generate_session_id, normalize_ws_root_url


def test_normalize_ws_root_url_strips_session_segment() -> None:
    assert normalize_ws_root_url("ws://127.0.0.1:8000/ws/local_user/local_session") == "ws://127.0.0.1:8000/ws/local_user"
    assert normalize_ws_root_url("wss://example.com/ws/local_user") == "wss://example.com/ws/local_user"


def test_build_ws_session_url_appends_session() -> None:
    assert build_ws_session_url("ws://127.0.0.1:8000/ws/local_user", "sess-1") == "ws://127.0.0.1:8000/ws/local_user/sess-1"


def test_generate_session_id_is_prefixed_and_randomish() -> None:
    first = generate_session_id()
    second = generate_session_id()

    assert first.startswith("local_session_")
    assert second.startswith("local_session_")
    assert first != second
