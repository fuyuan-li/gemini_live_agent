# app/server.py
import asyncio
import json
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.genai import types
from google.adk.events import Event, EventActions
from google.genai.errors import APIError
import traceback

from app.state.realtime_pointer import set_cursor
from .agents import root_agent
from app.runtime.genai_ws_sniffer import record_outbound, get_last_outbound
from app.runtime.cursor_payload import parse_cursor_payload

load_dotenv()

APP_NAME = "live_voice_agent"
INPUT_MIME = "audio/pcm;rate=16000"

def install_websockets_send_sniffer():
    import websockets.asyncio.connection as conn_mod
    Connection = conn_mod.Connection
    if getattr(Connection.send, "_sniffed", False):
        return

    _orig = Connection.send

    async def send(self, message, *args, **kwargs):
        record_outbound(message)
        return await _orig(self, message, *args, **kwargs)

    send._sniffed = True  # type: ignore[attr-defined]
    Connection.send = send  # type: ignore[assignment]

install_websockets_send_sniffer()

app = FastAPI()

session_service = InMemorySessionService()
runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=session_service,
)

@app.websocket("/ws/{user_id}/{session_id}")
async def ws(user_id: str, session_id: str, websocket: WebSocket) -> None:
    await websocket.accept()

    # Create or get session
    session = await session_service.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    if not session:
        session = await session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )

    # LiveRequestQueue: one per streaming session  [oai_citation:10‡Google GitHub](https://google.github.io/adk-docs/streaming/dev-guide/part1/)
    queue = LiveRequestQueue()

    # Audio-in / Audio-out streaming config  [oai_citation:11‡Google GitHub](https://google.github.io/adk-docs/streaming/dev-guide/part1/)
    run_config = RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=[types.Modality.AUDIO],
        # optional: transcriptions (handy for debugging)
        # input_audio_transcription=types.AudioTranscriptionConfig(),
        # output_audio_transcription=types.AudioTranscriptionConfig(),
    )

    async def upstream() -> None:
        """
        Receive:
          - binary frames: PCM16@16kHz audio chunks
          - text frames: JSON control messages (cursor updates)
        """
        try:
            while True:
                msg = await websocket.receive()

                # audio bytes
                b = msg.get("bytes")
                if b is not None:
                    if not b:
                        continue
                    blob = types.Blob(mime_type=INPUT_MIME, data=b)
                    queue.send_realtime(blob)
                    continue

                # control text (cursor)
                t = msg.get("text")
                if t is None:
                    continue

                try:
                    payload = json.loads(t)
                except Exception:
                    continue

                pos = parse_cursor_payload(payload)
                if pos is not None:
                    x_i, y_i = pos

                    # print("[cursor] recv", x_i, y_i, "sid=", session_id, "uid=", user_id)
                    await set_cursor(user_id=user_id, session_id=session_id, x=x_i, y=y_i)

                    # s2 = await session_service.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
                    # if s2:
                    #     print("[cursor] after append, session.state.cursor =", (s2.state or {}).get("cursor"))
                    # else:
                    #     print("[cursor] after append, session not found")

        except WebSocketDisconnect:
            pass

    async def downstream() -> None:
        """
        Consume ADK events and forward audio bytes back to client.
        Also print last outbound frame to Gemini when APIError happens (e.g., 1007).
        """
        try:
            async for event in runner.run_live(
                user_id=user_id,
                session_id=session_id,
                live_request_queue=queue,
                run_config=run_config,
            ):
                if not event.content or not event.content.parts:
                    continue
                for part in event.content.parts:
                    if not part.inline_data:
                        continue
                    mt = part.inline_data.mime_type
                    data = part.inline_data.data
                    if mt and mt.startswith("audio/pcm") and data is not None:
                        await websocket.send_bytes(data)

        except APIError as e:
            # This is the key "PRINT PRINT PRINT"
            last = get_last_outbound()
            print(f"[downstream] APIError: status_code={getattr(e, 'status_code', None)} message={e}")
            print(f"[downstream] LAST OUTBOUND (server->Gemini): {last}")
            traceback.print_exc()
            # re-raise so gather can see it (or swallow if you want)
            raise

        except Exception as e:
            last = get_last_outbound()
            print(f"[downstream] Unexpected exception: {type(e).__name__}: {e}")
            print(f"[downstream] LAST OUTBOUND (server->Gemini): {last}")
            traceback.print_exc()
            raise

    try:
        results = await asyncio.gather(upstream(), downstream(), return_exceptions=True)

        # Print exceptions so they don't disappear
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                print(f"[ws] task#{i} exception: {type(r).__name__}: {r}")

    finally:
        queue.close()
