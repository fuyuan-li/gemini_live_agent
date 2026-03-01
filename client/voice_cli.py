from __future__ import annotations

import argparse
import asyncio
import sys

import sounddevice as sd
import websockets

from client.cursor.provider import CursorProvider, HandCursorProvider, MouseCursorProvider
from client.ws_guard import OutboundTelemetry, WSSender

# Live audio requirements per ADK streaming guide:
# - Input: PCM16 mono @ 16kHz
# - Output: PCM16 mono @ 24kHz
IN_RATE = 16000
OUT_RATE = 24000
CHANNELS_IN = 1
CHANNELS_OUT = 1
DTYPE = "int16"

CHUNK_MS = 100
CHUNK_SAMPLES = int(IN_RATE * CHUNK_MS / 1000)
DEFAULT_WS_URL = "ws://127.0.0.1:8000/ws/local_user/local_session"


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Voice client with cursor streaming")

    p.add_argument("--ws-url", default=DEFAULT_WS_URL)

    p.add_argument("--cursor-source", choices=["hand", "mouse"], default="hand")
    p.add_argument("--cursor-send-hz", type=float, default=20.0)

    p.add_argument("--camera-index", type=int, default=0)
    p.add_argument("--hand-smoothing", type=float, default=0.35)
    p.add_argument("--cursor-stale-ms", type=int, default=400)
    p.add_argument("--hand-preview", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--hand-overlay", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--hand-overlay-radius", type=int, default=10)
    p.add_argument("--hand-mirror", action=argparse.BooleanOptionalAction, default=True)

    return p


async def cursor_sender(sender: WSSender, provider: CursorProvider, send_hz: float) -> None:
    interval = 1.0 / max(1.0, float(send_hz))

    while True:
        provider.pump_ui()
        cur = provider.get_cursor()
        if cur is not None:
            payload = {
                "type": "cursor",
                "x": cur.x,
                "y": cur.y,
                "source": cur.source,
                "ts": cur.ts,
            }
            if cur.confidence is not None:
                payload["confidence"] = cur.confidence
            await sender.send_json("cursor", payload)
        await asyncio.sleep(interval)


async def mic_sender(sender: WSSender) -> None:
    """
    Toggle talking with Enter.
    When talking, stream raw PCM16@16kHz bytes to the server as WS binary frames.
    """
    talking = False
    loop = asyncio.get_running_loop()
    q: asyncio.Queue[bytes] = asyncio.Queue()

    def callback(indata, frames, time_info, status) -> None:
        if status:
            pass
        if talking:
            q.put_nowait(bytes(indata))

    print("Press Enter to START talking, Enter again to STOP. Ctrl+C to quit.\n")

    with sd.RawInputStream(
        samplerate=IN_RATE,
        channels=CHANNELS_IN,
        dtype=DTYPE,
        blocksize=CHUNK_SAMPLES,
        callback=callback,
    ):
        while True:
            await loop.run_in_executor(None, sys.stdin.readline)
            talking = not talking
            print("🎙️  TALKING" if talking else "🛑  STOPPED")

            while talking:
                try:
                    chunk = await asyncio.wait_for(q.get(), timeout=0.25)
                    await sender.send_bytes("mic_chunk", chunk)
                except asyncio.TimeoutError:
                    continue


async def speaker_player(ws: websockets.ClientConnection) -> None:
    """
    Receive raw PCM16@24kHz bytes from server and play them.
    """
    with sd.RawOutputStream(
        samplerate=OUT_RATE,
        channels=CHANNELS_OUT,
        dtype=DTYPE,
        blocksize=0,
    ) as out:
        async for msg in ws:
            if isinstance(msg, bytes) and msg:
                out.write(msg)


def build_cursor_provider(args: argparse.Namespace):
    if args.cursor_source == "mouse":
        return MouseCursorProvider()

    return HandCursorProvider(
        camera_index=args.camera_index,
        smoothing=args.hand_smoothing,
        stale_timeout_s=max(0.0, args.cursor_stale_ms / 1000.0),
        tracker_start_timeout_s=8.0,
        mirror=args.hand_mirror,
        preview=args.hand_preview,
        overlay=args.hand_overlay,
        overlay_radius=args.hand_overlay_radius,
    )


async def run_client(args: argparse.Namespace) -> None:
    provider = build_cursor_provider(args)
    if not provider.start():
        raise RuntimeError(f"failed to start cursor provider: {provider.status()}")

    try:
        async with websockets.connect(
            args.ws_url,
            max_size=None,
            ping_interval=20,
            ping_timeout=20,
        ) as ws:
            telemetry = OutboundTelemetry()
            sender = WSSender(ws, telemetry)

            try:
                await asyncio.gather(
                    mic_sender(sender),
                    speaker_player(ws),
                    cursor_sender(sender, provider, args.cursor_send_hz),
                )
            except websockets.exceptions.ConnectionClosedError as exc:
                print(f"[voice_cli] WS CLOSED: code={exc.code}, reason={exc.reason}")
                print(f"[voice_cli] LAST OUTBOUND: {telemetry.last}")
                raise
    finally:
        provider.stop()


def main() -> None:
    args = build_arg_parser().parse_args()
    try:
        asyncio.run(run_client(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
