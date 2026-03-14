from __future__ import annotations
import numpy as np

IN_RATE = 16000
OUT_RATE = 24000
# frame_size = mic chunk size (100ms at 16kHz); must match CHUNK_SAMPLES
FRAME_SAMPLES = 1600
FILTER_LENGTH = 4096  # echo tail up to ~256ms


def _resample_24k_to_16k(pcm_24k: bytes) -> bytes:
    """Downsample 24kHz int16 PCM to 16kHz using linear interpolation."""
    arr = np.frombuffer(pcm_24k, dtype=np.int16)
    if len(arr) == 0:
        return b""
    n_out = len(arr) * IN_RATE // OUT_RATE
    if n_out == 0:
        return b""
    x_old = np.linspace(0.0, 1.0, len(arr))
    x_new = np.linspace(0.0, 1.0, n_out)
    return np.interp(x_new, x_old, arr).astype(np.int16).tobytes()


class AcousticEchoCanceller:
    """
    Wraps speexdsp EchoCanceller.  Falls back to pass-through if speexdsp
    is not installed (so the app still runs without it).
    """

    def __init__(self) -> None:
        self._ec = None
        self._ref_buf = bytearray()
        try:
            from speexdsp import EchoCanceller
            self._ec = EchoCanceller.create(
                frame_size=FRAME_SAMPLES,
                filter_length=FILTER_LENGTH,
                sample_rate=IN_RATE,
            )
        except Exception:
            pass  # speexdsp not available; push_speaker / process become no-ops

    @property
    def active(self) -> bool:
        return self._ec is not None

    def push_speaker(self, pcm_24k: bytes) -> None:
        """Called when server sends TTS audio. Resamples and buffers as reference."""
        if self._ec is None or not pcm_24k:
            return
        self._ref_buf.extend(_resample_24k_to_16k(pcm_24k))

    def process(self, mic_frame: bytes) -> bytes:
        """
        Remove echo from mic_frame.
        Returns cleaned bytes (same length); falls back to silence if not enough
        reference data yet (first few frames during warmup).
        """
        if self._ec is None:
            return mic_frame
        need = len(mic_frame)
        if len(self._ref_buf) < need:
            # Not enough reference yet — return silence to avoid false input
            return bytes(need)
        ref = bytes(self._ref_buf[:need])
        del self._ref_buf[:need]
        try:
            return self._ec.process(mic_frame, ref)
        except Exception:
            return mic_frame
