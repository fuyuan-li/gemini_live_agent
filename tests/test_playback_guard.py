from array import array

from client.playback_guard import PlaybackGuard
from client.playback_guard import PlaybackGuardConfig


def _pcm(amplitude: int, samples: int = 1600) -> bytes:
    return array("h", [amplitude] * samples).tobytes()


def test_playback_guard_allows_mic_when_not_playing() -> None:
    guard = PlaybackGuard()

    decision = guard.should_send_mic_chunk(_pcm(600), now=10.0)

    assert decision.send is True
    assert decision.reason == "idle"


def test_playback_guard_suppresses_low_rms_echo_during_recent_playback() -> None:
    guard = PlaybackGuard(
        PlaybackGuardConfig(
            playback_tail_ms=350,
            mic_floor_rms=900,
            echo_max_ratio=0.55,
            barge_in_rms=2200,
            barge_in_ratio=1.20,
            barge_in_chunks=2,
            barge_in_hold_ms=900,
        )
    )
    guard.note_playback_chunk(_pcm(3000), now=1.0)

    decision = guard.should_send_mic_chunk(_pcm(700), now=1.1)

    assert decision.send is False
    assert decision.reason == "playback_suppressed"


def test_playback_guard_requires_consecutive_loud_chunks_for_barge_in() -> None:
    guard = PlaybackGuard(
        PlaybackGuardConfig(
            playback_tail_ms=350,
            mic_floor_rms=900,
            echo_max_ratio=0.55,
            barge_in_rms=2200,
            barge_in_ratio=1.20,
            barge_in_chunks=2,
            barge_in_hold_ms=900,
        )
    )
    guard.note_playback_chunk(_pcm(2500), now=1.0)

    first = guard.should_send_mic_chunk(_pcm(3200), now=1.1)
    second = guard.should_send_mic_chunk(_pcm(3200), now=1.2)
    third = guard.should_send_mic_chunk(_pcm(1200), now=1.25)

    assert first.send is False
    assert first.reason == "playback_suppressed"
    assert second.send is True
    assert second.reason == "barge_in_detected"
    assert third.send is True
    assert third.reason == "barge_in_hold"
