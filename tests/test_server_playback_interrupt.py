from array import array

from app.live.audio_gate import SessionAudioGate
from app.live.resettable_queue import ResettableLiveRequestQueue
from app.server import _note_playback_output
from app.server import _playback_interrupt_ready


def _pcm(amplitude: int, samples: int = 1600) -> bytes:
    return array("h", [amplitude] * samples).tobytes()


def test_note_playback_output_keeps_peak_rms_within_tail_window() -> None:
    gate = SessionAudioGate(queue=ResettableLiveRequestQueue())

    _note_playback_output(gate, chunk=_pcm(4143), now=1.0)
    _note_playback_output(gate, chunk=_pcm(20), now=1.1)

    assert gate.playback_rms == 4143
    assert gate.playback_active_until > 1.1


def test_playback_interrupt_requires_stronger_confirmed_opening() -> None:
    gate = SessionAudioGate(queue=ResettableLiveRequestQueue())
    _note_playback_output(gate, chunk=_pcm(4143), now=1.0)

    assert _playback_interrupt_ready(gate, rms=5226, now=1.1) is False
    assert _playback_interrupt_ready(gate, rms=5226, now=1.2) is True

    gate = SessionAudioGate(queue=ResettableLiveRequestQueue())
    _note_playback_output(gate, chunk=_pcm(4143), now=1.0)
    assert _playback_interrupt_ready(gate, rms=2000, now=1.1) is False
    assert _playback_interrupt_ready(gate, rms=2000, now=1.2) is False
