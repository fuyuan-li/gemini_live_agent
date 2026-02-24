import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.genai import types

from agents import root_agent
from agents.cursor_state import set_cursor

load_dotenv()

APP_NAME = "live_voice_agent"
INPUT_MIME = "audio/pcm;rate=16000"

app = FastAPI()

session_service = InMemorySessionService()
runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=session_service,
)

INPUT_MIME = "audio/pcm;rate=16000"   # mic input requirement  [oai_citation:9‡Google GitHub](https://google.github.io/adk-docs/streaming/dev-guide/part5/)


@app.websocket("/ws/{user_id}/{session_id}")
async def ws(user_id: str, session_id: str, websocket: WebSocket) -> None:
    await websocket.accept()

    # Create or get session
    session = await session_service.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    if not session:
        await session_service.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)

    # LiveRequestQueue: one per streaming session  [oai_citation:10‡Google GitHub](https://google.github.io/adk-docs/streaming/dev-guide/part1/)
    queue = LiveRequestQueue()

    # Audio-in / Audio-out streaming config  [oai_citation:11‡Google GitHub](https://google.github.io/adk-docs/streaming/dev-guide/part1/)
    run_config = RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=["AUDIO"],
        # optional: transcriptions (handy for debugging)
        # input_audio_transcription=types.AudioTranscriptionConfig(),
        # output_audio_transcription=types.AudioTranscriptionConfig(),
    )

    async def upstream() -> None:
        """
        Receive binary audio frames from client and forward to ADK LiveRequestQueue.
        Receive:
          - binary frames: PCM16@16kHz audio chunks
          - text frames: JSON control messages (cursor updates)
        """
        try:
            while True:
                msg = await websocket.receive()
                if "bytes" in msg and msg["bytes"] is not None:
                    audio_bytes: bytes = msg["bytes"]
                    if not audio_bytes:
                        continue
                    blob = types.Blob(mime_type=INPUT_MIME, data=audio_bytes)
                    queue.send_realtime(blob)
                    continue

                # control text (cursor)
                if "text" in msg and msg["text"] is not None:
                    try:
                        payload = json.loads(msg["text"])
                    except Exception:
                        continue
                    if payload.get("type") == "cursor":
                        x = payload.get("x")
                        y = payload.get("y")
                        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                            await set_cursor(user_id, session_id, int(x), int(y))
        except WebSocketDisconnect:
            pass

    async def downstream() -> None:
        """
        Consume ADK events and forward *audio bytes* back to the client.
        Audio is in event.content.parts[].inline_data.data  [oai_citation:12‡Google GitHub](https://google.github.io/adk-docs/streaming/dev-guide/part3/)
        """
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

    try:
        await asyncio.gather(upstream(), downstream(), return_exceptions=True)
    finally:
        queue.close()