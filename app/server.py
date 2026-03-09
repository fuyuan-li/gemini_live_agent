# app/server.py
import asyncio
import json
import logging
import os
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
from app.live.trace import log_trace_event, make_cursor_ack
from app.runtime.genai_ws_sniffer import get_last_outbound, get_recent_outbound, record_outbound
from app.runtime.cursor_payload import parse_cursor_payload
from app.runtime.session_bridge import (
    emit_server_trace,
    handle_tool_result,
    register_bridge,
    send_session_meta,
    unregister_bridge,
)

load_dotenv()

APP_NAME = "live_voice_agent"
INPUT_MIME = "audio/pcm;rate=16000"
SERVICE_NAME = os.getenv("K_SERVICE", "local-dev")
SERVICE_REVISION = os.getenv("K_REVISION", "local-revision")
GIT_COMMIT_SHA = os.getenv("GIT_COMMIT_SHA", "unknown")
AUDIO_LOG_EVERY_CHUNKS = int(os.getenv("AUDIO_LOG_EVERY_CHUNKS", "20"))
CURSOR_TRACE_INTERVAL_S = float(os.getenv("CURSOR_TRACE_INTERVAL_S", "1.0"))
CURSOR_TRACE_MIN_DELTA_PX = int(os.getenv("CURSOR_TRACE_MIN_DELTA_PX", "24"))
EXPECTED_AUDIO_CHUNK_BYTES = 3200
logger = logging.getLogger("app.server.live")

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
    bridge = await register_bridge(user_id=user_id, session_id=session_id, websocket=websocket)
    logger.info(
        "[session] accepted ws user=%s session=%s service=%s revision=%s commit=%s model=%s input_mime=%s",
        user_id,
        session_id,
        SERVICE_NAME,
        SERVICE_REVISION,
        GIT_COMMIT_SHA,
        getattr(root_agent, "model", "unknown"),
        INPUT_MIME,
    )
    await send_session_meta(
        user_id=user_id,
        session_id=session_id,
        service=SERVICE_NAME,
        revision=SERVICE_REVISION,
        commit=GIT_COMMIT_SHA,
    )
    await emit_server_trace(
        user_id=user_id,
        session_id=session_id,
        request_id=session_id,
        event="session_connected",
        status="ok",
        summary=f"connected to {SERVICE_NAME}@{SERVICE_REVISION}",
        agent_name=root_agent.name,
    )

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
            audio_chunk_count = 0
            audio_bytes_total = 0
            last_cursor_trace_ts = 0.0
            last_logged_cursor: tuple[int, int] | None = None
            while True:
                msg = await websocket.receive()

                # audio bytes
                b = msg.get("bytes")
                if b is not None:
                    if not b:
                        continue
                    audio_chunk_count += 1
                    audio_bytes_total += len(b)
                    if len(b) != EXPECTED_AUDIO_CHUNK_BYTES:
                        logger.warning(
                            "[upstream.audio] unusual chunk size user=%s session=%s chunk=%s bytes=%s expected=%s",
                            user_id,
                            session_id,
                            audio_chunk_count,
                            len(b),
                            EXPECTED_AUDIO_CHUNK_BYTES,
                        )
                    elif audio_chunk_count == 1 or audio_chunk_count % AUDIO_LOG_EVERY_CHUNKS == 0:
                        logger.info(
                            "[upstream.audio] user=%s session=%s chunks=%s total_bytes=%s last_chunk=%s",
                            user_id,
                            session_id,
                            audio_chunk_count,
                            audio_bytes_total,
                            len(b),
                        )
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

                if payload.get("type") == "tool_result":
                    logger.info(
                        "[upstream.tool_result] user=%s session=%s call_id=%s ok=%s",
                        user_id,
                        session_id,
                        payload.get("call_id"),
                        payload.get("ok"),
                    )
                    await handle_tool_result(user_id=user_id, session_id=session_id, payload=payload)
                    continue

                pos = parse_cursor_payload(payload)
                if pos is not None:
                    x_i, y_i = pos

                    await set_cursor(user_id=user_id, session_id=session_id, x=x_i, y=y_i)
                    request_id = f"cursor:{payload.get('client_msg_id', 'na')}"
                    await bridge.send_json(
                        make_cursor_ack(
                            session_id=session_id,
                            request_id=request_id,
                            x=x_i,
                            y=y_i,
                        )
                    )
                    now = time.time()
                    delta_ok = (
                        last_logged_cursor is None
                        or abs(x_i - last_logged_cursor[0]) >= CURSOR_TRACE_MIN_DELTA_PX
                        or abs(y_i - last_logged_cursor[1]) >= CURSOR_TRACE_MIN_DELTA_PX
                    )
                    if delta_ok and now - last_cursor_trace_ts >= CURSOR_TRACE_INTERVAL_S:
                        await emit_server_trace(
                            user_id=user_id,
                            session_id=session_id,
                            request_id=request_id,
                            event="cursor_received",
                            status="ok",
                            summary=f"cursor=({x_i},{y_i})",
                            cursor={"x": x_i, "y": y_i},
                        )
                        last_cursor_trace_ts = now
                        last_logged_cursor = (x_i, y_i)
                    continue

                logger.info(
                    "[upstream.text] user=%s session=%s ignored payload keys=%s",
                    user_id,
                    session_id,
                    list(payload.keys())[:8],
                )

        except WebSocketDisconnect:
            logger.info("[session] upstream disconnect user=%s session=%s", user_id, session_id)
            pass

    async def downstream() -> None:
        """
        Consume ADK events and forward audio bytes back to client.
        Also print last outbound frame to Gemini when APIError happens (e.g., 1007).
        """
        try:
            logger.info(
                "[downstream] run_live start user=%s session=%s streaming_mode=%s response_modalities=%s",
                user_id,
                session_id,
                StreamingMode.BIDI,
                ["AUDIO"],
            )
            output_chunk_count = 0
            output_bytes_total = 0
            event_count = 0
            async for event in runner.run_live(
                user_id=user_id,
                session_id=session_id,
                live_request_queue=queue,
                run_config=run_config,
            ):
                event_count += 1
                if not event.content or not event.content.parts:
                    continue
                for part in event.content.parts:
                    if not part.inline_data:
                        continue
                    mt = part.inline_data.mime_type
                    data = part.inline_data.data
                    if mt and mt.startswith("audio/pcm") and data is not None:
                        output_chunk_count += 1
                        output_bytes_total += len(data)
                        if output_chunk_count == 1 or output_chunk_count % AUDIO_LOG_EVERY_CHUNKS == 0:
                            logger.info(
                                "[downstream.audio] user=%s session=%s events=%s chunks=%s total_bytes=%s last_chunk=%s mime=%s",
                                user_id,
                                session_id,
                                event_count,
                                output_chunk_count,
                                output_bytes_total,
                                len(data),
                                mt,
                            )
                        await bridge.send_bytes(data)

        except APIError as e:
            # This is the key "PRINT PRINT PRINT"
            last = get_last_outbound()
            recent = get_recent_outbound()
            await emit_server_trace(
                user_id=user_id,
                session_id=session_id,
                request_id=session_id,
                event="session_error",
                status="error",
                summary=f"APIError status={getattr(e, 'status_code', None)} {e}",
                agent_name=root_agent.name,
            )
            logger.error(
                "[downstream] APIError user=%s session=%s status_code=%s message=%s",
                user_id,
                session_id,
                getattr(e, "status_code", None),
                e,
            )
            logger.error("[downstream] recent outbound frames to Gemini: %s", recent)
            print(f"[downstream] APIError: status_code={getattr(e, 'status_code', None)} message={e}")
            print(f"[downstream] LAST OUTBOUND (server->Gemini): {last}")
            traceback.print_exc()
            # re-raise so gather can see it (or swallow if you want)
            raise

        except Exception as e:
            last = get_last_outbound()
            recent = get_recent_outbound()
            await emit_server_trace(
                user_id=user_id,
                session_id=session_id,
                request_id=session_id,
                event="session_error",
                status="error",
                summary=f"{type(e).__name__}: {e}",
                agent_name=root_agent.name,
            )
            logger.exception(
                "[downstream] Unexpected exception user=%s session=%s: %s",
                user_id,
                session_id,
                e,
            )
            logger.error("[downstream] recent outbound frames to Gemini: %s", recent)
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
                logger.error(
                    "[session] task exception user=%s session=%s task=%s type=%s message=%s",
                    user_id,
                    session_id,
                    i,
                    type(r).__name__,
                    r,
                )

    finally:
        event = {
            "event_id": f"disconnect-{session_id}",
            "request_id": session_id,
            "session_id": session_id,
            "source": "server",
            "event": "session_disconnected",
            "status": "ok",
            "summary": "websocket disconnected",
            "ts": time.time(),
        }
        log_trace_event(event)
        logger.info("[session] closing user=%s session=%s", user_id, session_id)
        try:
            await bridge.send_json({"type": "trace_event", **event})
        except Exception:
            pass
        queue.close()
        await unregister_bridge(user_id=user_id, session_id=session_id, bridge=bridge)
