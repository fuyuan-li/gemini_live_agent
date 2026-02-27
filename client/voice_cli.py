import asyncio
import sys
from typing import Any

import sounddevice as sd
import websockets

import json
import time
from pynput.mouse import Controller
from client.ws_guard import OutboundTelemetry, WSSender

_mouse = Controller()

WS_URL = "ws://127.0.0.1:8000/ws/local_user/local_session"

# Live audio requirements per ADK streaming guide:
# - Input: PCM16 mono @ 16kHz
# - Output: PCM16 mono @ 24kHz
IN_RATE = 16000
OUT_RATE = 24000
CHANNELS_IN = 1
CHANNELS_OUT = 1
DTYPE = "int16"  # PCM16

CHUNK_MS = 100
CHUNK_SAMPLES = int(IN_RATE * CHUNK_MS / 1000)


def get_cursor_pos():
    x, y = _mouse.position
    return int(x), int(y)


async def cursor_sender(sender: WSSender):
    while True:
        x, y = get_cursor_pos()
        await sender.send_json("cursor", {"type": "cursor", "x": x, "y": y})
        await asyncio.sleep(0.05)  # 20Hz

async def mic_sender(sender: WSSender) -> None:
    """
    Toggle talking with Enter.
    When talking, stream raw PCM16@16kHz bytes to the server as WS binary frames.
    """
    talking = False
    loop = asyncio.get_running_loop()
    q: asyncio.Queue[bytes] = asyncio.Queue()

    def callback(indata, frames, time, status):
        # indata is a raw bytes buffer (because RawInputStream)
        if status:
            # ignore overflow warnings
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
            # Wait for Enter (non-blocking for the event loop)
            await loop.run_in_executor(None, sys.stdin.readline)
            talking = not talking
            print("🎙️  TALKING" if talking else "🛑  STOPPED")

            # While talking, send chunks as they arrive
            while talking:
                try:
                    chunk = await asyncio.wait_for(q.get(), timeout=0.25)
                    await sender.send_bytes("mic_chunk", chunk)
                except asyncio.TimeoutError:
                    # no audio chunk yet
                    continue


async def speaker_player(ws: websockets.ClientConnection) -> None:
    """
    Receive raw PCM16@24kHz bytes from server and play them.
    """
    with sd.RawOutputStream(
        samplerate=OUT_RATE,
        channels=CHANNELS_OUT,
        dtype=DTYPE,
        blocksize=0,  # let PortAudio choose
    ) as out:
        async for msg in ws:
            if isinstance(msg, bytes) and msg:
                out.write(msg)
            # ignore text/control frames for now


async def main() -> None:
    async with websockets.connect(
        WS_URL,
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
                cursor_sender(sender),
            )
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"[voice_cli] WS CLOSED: code={e.code}, reason={e.reason}")
            print(f"[voice_cli] LAST OUTBOUND: {telemetry.last}")
            raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass