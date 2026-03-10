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
from app.live.trace import log_trace_event, make_cursor_ack, parse_trace_payload
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


def _cloud_info(message: str) -> None:
    logger.info(message)
    print(message)

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
    _cloud_info(
        "[session] accepted ws "
        f"user={user_id} session={session_id} service={SERVICE_NAME} "
        f"revision={SERVICE_REVISION} commit={GIT_COMMIT_SHA} "
        f"model={getattr(root_agent, 'model', 'unknown')} input_mime={INPUT_MIME}"
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
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
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
                        _cloud_info(
                            "[upstream.audio] unusual chunk size "
                            f"user={user_id} session={session_id} chunk={audio_chunk_count} "
                            f"bytes={len(b)} expected={EXPECTED_AUDIO_CHUNK_BYTES}"
                        )
                    elif audio_chunk_count == 1 or audio_chunk_count % AUDIO_LOG_EVERY_CHUNKS == 0:
                        _cloud_info(
                            "[upstream.audio] "
                            f"user={user_id} session={session_id} chunks={audio_chunk_count} "
                            f"total_bytes={audio_bytes_total} last_chunk={len(b)}"
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
                    _cloud_info(
                        "[upstream.tool_result] "
                        f"user={user_id} session={session_id} call_id={payload.get('call_id')} ok={payload.get('ok')}"
                    )
                    await handle_tool_result(user_id=user_id, session_id=session_id, payload=payload)
                    continue

                client_trace = parse_trace_payload(
                    payload,
                    expected_type="client_trace",
                    expected_source="client",
                    expected_session_id=session_id,
                )
                if client_trace is not None:
                    log_trace_event(client_trace)
                    continue
                if payload.get("type") == "client_trace":
                    _cloud_info(
                        "[upstream.client_trace] dropped invalid client trace "
                        f"user={user_id} session={session_id} keys={list(payload.keys())[:10]}"
                    )
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

                _cloud_info(
                    "[upstream.text] "
                    f"user={user_id} session={session_id} ignored payload keys={list(payload.keys())[:8]}"
                )

        except WebSocketDisconnect:
            _cloud_info(f"[session] upstream disconnect user={user_id} session={session_id}")
            pass

    async def downstream() -> None:
        """
        Consume ADK events and forward audio bytes back to client.
        Also print last outbound frame to Gemini when APIError happens (e.g., 1007).
        """
        try:
            _cloud_info(
                "[downstream] run_live start "
                f"user={user_id} session={session_id} streaming_mode={StreamingMode.BIDI} "
                "response_modalities=['AUDIO']"
            )
            output_chunk_count = 0
            output_bytes_total = 0
            event_count = 0
            last_input_transcript = ""
            last_output_transcript = ""
            async for event in runner.run_live(
                user_id=user_id,
                session_id=session_id,
                live_request_queue=queue,
                run_config=run_config,
            ):
                event_count += 1
                author = getattr(event, "author", None)
                turn_complete = bool(getattr(event, "turn_complete", False))
                interrupted = bool(getattr(event, "interrupted", False))
                input_tx = getattr(event, "input_transcription", None)
                output_tx = getattr(event, "output_transcription", None)

                if input_tx is not None:
                    input_text = str(getattr(input_tx, "text", "") or "").strip()
                    if input_text and input_text != last_input_transcript:
                        _cloud_info(
                            "[downstream.transcript.user] "
                            f"user={user_id} session={session_id} author={author} "
                            f"text={input_text!r} turn_complete={turn_complete} interrupted={interrupted}"
                        )
                        last_input_transcript = input_text
                        await emit_server_trace(
                            user_id=user_id,
                            session_id=session_id,
                            request_id=session_id,
                            event="user_spoke",
                            status="ok",
                            summary=input_text,
                            agent_name=str(author) if author else None,
                        )

                if output_tx is not None:
                    output_text = str(getattr(output_tx, "text", "") or "").strip()
                    if output_text and output_text != last_output_transcript:
                        _cloud_info(
                            "[downstream.transcript.model] "
                            f"user={user_id} session={session_id} author={author} "
                            f"text={output_text!r} turn_complete={turn_complete} interrupted={interrupted}"
                        )
                        last_output_transcript = output_text
                        await emit_server_trace(
                            user_id=user_id,
                            session_id=session_id,
                            request_id=session_id,
                            event="agent_spoke",
                            status="ok",
                            summary=output_text,
                            agent_name=str(author) if author else None,
                        )

                if turn_complete or interrupted:
                    _cloud_info(
                        "[downstream.event] "
                        f"user={user_id} session={session_id} author={author} "
                        f"turn_complete={turn_complete} interrupted={interrupted} "
                        f"finish_reason={getattr(event, 'finish_reason', None)}"
                    )
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
                            _cloud_info(
                                "[downstream.audio] "
                                f"user={user_id} session={session_id} events={event_count} "
                                f"chunks={output_chunk_count} total_bytes={output_bytes_total} "
                                f"last_chunk={len(data)} mime={mt}"
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
            _cloud_info(
                "[downstream] APIError "
                f"user={user_id} session={session_id} status_code={getattr(e, 'status_code', None)} message={e}"
            )
            _cloud_info(f"[downstream] recent outbound frames to Gemini: {recent}")
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
            _cloud_info(
                f"[downstream] Unexpected exception user={user_id} session={session_id}: {type(e).__name__}: {e}"
            )
            _cloud_info(f"[downstream] recent outbound frames to Gemini: {recent}")
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
                _cloud_info(
                    "[session] task exception "
                    f"user={user_id} session={session_id} task={i} type={type(r).__name__} message={r}"
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
        _cloud_info(f"[session] closing user={user_id} session={session_id}")
        try:
            await bridge.send_json({"type": "trace_event", **event})
        except Exception:
            pass
        queue.close()
        await unregister_bridge(user_id=user_id, session_id=session_id, bridge=bridge)
        try:
            await session_service.delete_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
            _cloud_info(f"[session] deleted user={user_id} session={session_id}")
        except Exception as exc:
            _cloud_info(
                "[session] delete failed "
                f"user={user_id} session={session_id} type={type(exc).__name__} message={exc}"
            )
