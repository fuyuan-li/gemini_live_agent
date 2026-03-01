from app.runtime.cursor_payload import parse_cursor_payload


def test_parse_cursor_payload_accepts_required_fields() -> None:
    payload = {"type": "cursor", "x": 12, "y": 34}
    assert parse_cursor_payload(payload) == (12, 34)


def test_parse_cursor_payload_accepts_optional_fields() -> None:
    payload = {
        "type": "cursor",
        "x": 12.8,
        "y": 34.2,
        "source": "hand",
        "confidence": 0.93,
        "ts": 1730000000.0,
    }
    assert parse_cursor_payload(payload) == (12, 34)


def test_parse_cursor_payload_rejects_invalid() -> None:
    assert parse_cursor_payload({"type": "not_cursor", "x": 1, "y": 2}) is None
    assert parse_cursor_payload({"type": "cursor", "x": "1", "y": 2}) is None
