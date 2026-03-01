from client.cursor.mapper import CursorMapper, ScreenGeometry


def test_mapper_clamps_to_screen_bounds() -> None:
    mapper = CursorMapper(
        screen_geometry=ScreenGeometry(width=100, height=80),
        smoothing=1.0,
        stale_timeout_s=0.5,
    )

    cur = mapper.update_from_normalized(1.4, -0.1, ts=1.0)
    assert cur.x == 99
    assert cur.y == 0


def test_mapper_applies_smoothing() -> None:
    mapper = CursorMapper(
        screen_geometry=ScreenGeometry(width=101, height=51),
        smoothing=0.5,
        stale_timeout_s=0.5,
    )

    first = mapper.update_from_normalized(0.0, 0.0, ts=1.0)
    second = mapper.update_from_normalized(1.0, 1.0, ts=2.0)

    assert first.x == 0
    assert first.y == 0
    assert second.x == 50
    assert second.y == 25


def test_mapper_returns_fallback_before_stale_timeout() -> None:
    mapper = CursorMapper(
        screen_geometry=ScreenGeometry(width=100, height=100),
        smoothing=1.0,
        stale_timeout_s=0.5,
    )

    mapper.update_from_normalized(0.1, 0.2, ts=10.0)
    assert mapper.get_fallback(now_ts=10.2) is not None
    assert mapper.get_fallback(now_ts=10.6) is None
