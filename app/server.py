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

from agents import root_agent

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
        response_modalities=["AUDIO"],
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

                if payload.get("type") == "cursor":
                    x = payload.get("x")
                    y = payload.get("y")
                    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                        x_i, y_i = int(x), int(y)

                        # ✅ 用 system event 写入 session.state（通过 state_delta）
                        actions = EventActions(
                            state_delta={"cursor": {"x": x_i, "y": y_i, "ts": time.time()}}
                        )
                        system_event = Event(
                            invocation_id=f"cursor_{time.time()}",
                            author="system",
                            actions=actions,
                            timestamp=time.time(),
                        )

                        # ✅ append_event 签名：append_event(session, event)
                        await session_service.append_event(session=session, event=system_event)

        except WebSocketDisconnect:
            pass

    async def downstream() -> None:
        """
        Consume ADK events and forward audio bytes back to client.
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