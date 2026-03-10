from __future__ import annotations

import audioop
from dataclasses import dataclass


@dataclass
class PlaybackGuardConfig:
    playback_tail_ms: int = 350
    echo_max_ratio: float = 0.55
    mic_floor_rms: int = 900
    barge_in_ratio: float = 1.20
    barge_in_rms: int = 2200
    barge_in_chunks: int = 2
    barge_in_hold_ms: int = 900


@dataclass
class PlaybackDecision:
    send: bool
    reason: str
    mic_rms: int
    playback_rms: int


class PlaybackGuard:
    def __init__(self, config: PlaybackGuardConfig | None = None) -> None:
        self.config = config or PlaybackGuardConfig()
        self.playback_active_until = 0.0
        self.last_playback_rms = 0
        self.barge_in_streak = 0
        self.barge_in_hold_until = 0.0

    def reset(self) -> None:
        self.playback_active_until = 0.0
        self.last_playback_rms = 0
        self.barge_in_streak = 0
        self.barge_in_hold_until = 0.0

    def note_playback_chunk(self, chunk: bytes, *, now: float) -> int:
        rms = pcm16_rms(chunk)
        if rms > 0:
            self.last_playback_rms = rms
            tail_s = self.config.playback_tail_ms / 1000.0
            self.playback_active_until = max(self.playback_active_until, now + tail_s)
        return rms

    def should_send_mic_chunk(self, chunk: bytes, *, now: float) -> PlaybackDecision:
        mic_rms = pcm16_rms(chunk)
        playback_rms = self.last_playback_rms

        if now < self.barge_in_hold_until:
            return PlaybackDecision(
                send=True,
                reason="barge_in_hold",
                mic_rms=mic_rms,
                playback_rms=playback_rms,
            )

        if now >= self.playback_active_until or playback_rms <= 0:
            self.barge_in_streak = 0
            return PlaybackDecision(
                send=True,
                reason="idle",
                mic_rms=mic_rms,
                playback_rms=playback_rms,
            )

        echo_ceiling = max(
            self.config.mic_floor_rms,
            int(playback_rms * self.config.echo_max_ratio),
        )
        if mic_rms <= echo_ceiling:
            self.barge_in_streak = 0
            return PlaybackDecision(
                send=False,
                reason="playback_suppressed",
                mic_rms=mic_rms,
                playback_rms=playback_rms,
            )

        barge_in_threshold = max(
            self.config.barge_in_rms,
            int(playback_rms * self.config.barge_in_ratio),
        )
        if mic_rms >= barge_in_threshold:
            self.barge_in_streak += 1
            if self.barge_in_streak >= self.config.barge_in_chunks:
                self.barge_in_streak = 0
                self.barge_in_hold_until = now + (self.config.barge_in_hold_ms / 1000.0)
                return PlaybackDecision(
                    send=True,
                    reason="barge_in_detected",
                    mic_rms=mic_rms,
                    playback_rms=playback_rms,
                )

        return PlaybackDecision(
            send=False,
            reason="playback_suppressed",
            mic_rms=mic_rms,
            playback_rms=playback_rms,
        )


def pcm16_rms(chunk: bytes) -> int:
    if not chunk:
        return 0
    return int(audioop.rms(chunk, 2))
