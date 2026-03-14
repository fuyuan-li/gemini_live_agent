from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from typing import Optional

import numpy as np
import sounddevice as sd
import websockets

from client.aec import AcousticEchoCanceller
from client.companion_state import CompanionState
from client.cursor.provider import HandCursorProvider
from client.local_executor import LocalToolExecutor
from client.session_ids import build_ws_session_url, generate_session_id, normalize_ws_root_url
from client.ws_guard import OutboundTelemetry, WSSender


IN_RATE = 16000
OUT_RATE = 24000
CHANNELS_IN = 1
CHANNELS_OUT = 1
DTYPE = "int16"
CHUNK_MS = 100
CHUNK_SAMPLES = int(IN_RATE * CHUNK_MS / 1000)
RECONNECT_DELAY_S = 2.0
# Echo gate: suppress mic until TTS audio finishes playing (+ this tail)
TTS_TAIL_S = 0.5
CLIENT_TRACE_EVENTS = {
    "camera_started",
    "session_connected",
    "session_disconnected",
    "session_error",
    "audio_stream_started",
    "audio_stream_muted",
    "audio_stream_unmuted",
    "audio_gate_closed",
    "audio_gate_opened",
    "session_reconnect_requested",
    "tool_result_received",
}
CLIENT_TRACE_MAX_BACKLOG = 256


class CompanionRuntime:
    def __init__(
        self,
        *,
        ws_url: str,
        provider: HandCursorProvider,
        state: CompanionState,
        cursor_send_hz: float = 20.0,
    ) -> None:
        self.ws_root_url = normalize_ws_root_url(ws_url)
        self.provider = provider
        self.state = state
        self.cursor_send_hz = float(max(1.0, cursor_send_hz))
        self.cursor_source = str(self.provider.status().get("source", "hand"))

        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_evt = threading.Event()
        self._stop_async: Optional[asyncio.Event] = None
        self._reconnect_async: Optional[asyncio.Event] = None
        self._mic_queue: Optional[asyncio.Queue[bytes]] = None
        self._audio_gate_open = True
        self._client_trace_lock = threading.Lock()
        self._pending_client_traces: deque[dict[str, object]] = deque(maxlen=CLIENT_TRACE_MAX_BACKLOG)
        self.state.set_local_trace_listener(self._queue_client_trace)
        self._aec = AcousticEchoCanceller()
        self._tts_play_until: float = 0.0  # monotonic time when TTS audio will finish playing
        self._output_latency_s: float = 0.05  # updated when output stream opens

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        print(f"[AEC] active={self._aec.active}" + ("" if self._aec.active else " (install speexdsp for echo cancellation)"))
        self.state.record_local_event(
            request_id=self.state.session_id,
            event="camera_started",
            status="ok",
            summary="camera tracker started",
        )
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_evt.set()
        if self._loop is not None and self._stop_async is not None:
            self._loop.call_soon_threadsafe(self._stop_async.set)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self.state.set_connected(False)

    def toggle_mute(self) -> bool:
        muted = self.state.toggle_muted()
        self.state.record_local_event(
            request_id=self.state.session_id,
            event="audio_stream_muted" if muted else "audio_stream_unmuted",
            status="ok",
            summary="muted" if muted else "unmuted",
        )
        return muted

    def request_reconnect(self) -> None:
        self.state.record_local_event(
            request_id=self.state.session_id,
            event="session_reconnect_requested",
            status="ok",
            summary="manual reconnect requested",
        )
        if self._loop is not None and self._reconnect_async is not None:
            self._loop.call_soon_threadsafe(self._reconnect_async.set)

    def poll_capture(self) -> None:
        self.provider.pump_ui()
        cursor = self.provider.get_cursor()
        fingertip = self.provider.tracker.get_latest_sample()
        self.state.update_local_capture(cursor=cursor, fingertip=fingertip)

    def get_preview_frame(self):
        return self.provider.tracker.get_preview_frame()

    def _thread_main(self) -> None:
        asyncio.run(self._run_forever())

    async def _run_forever(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop_async = asyncio.Event()
        self._reconnect_async = asyncio.Event()
        first_attempt = True
        while not self._stop_evt.is_set():
            if first_attempt:
                first_attempt = False
            else:
                self._rotate_session()
            telemetry = OutboundTelemetry()
            current_ws_url = build_ws_session_url(self.ws_root_url, self.state.session_id)
            try:
                async with websockets.connect(
                    current_ws_url,
                    max_size=None,
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:
                    self._audio_gate_open = True
                    self.state.set_connected(True)
                    self.state.record_local_event(
                        request_id=self.state.session_id,
                        event="session_connected",
                        status="ok",
                        summary="companion connected",
                        agent_name="concierge",
                    )
                    self._reconnect_async.clear()
                    sender = WSSender(ws, telemetry)
                    executor = LocalToolExecutor(
                        provider=self.provider,
                        sender=sender,
                        cursor_supplier=self.state.get_local_cursor_xy,
                        event_callback=self._executor_event_callback,
                    )
                    tasks = [
                        asyncio.create_task(self._mic_sender(sender)),
                        asyncio.create_task(self._receiver_loop(ws, executor)),
                        asyncio.create_task(self._cursor_sender(sender)),
                        asyncio.create_task(self._client_trace_sender(sender)),
                        asyncio.create_task(self._reconnect_watcher(ws)),
                    ]
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in pending:
                        task.cancel()
                    for task in done:
                        if task.cancelled():
                            continue
                        exc = task.exception()
                        if exc is not None and not isinstance(exc, asyncio.CancelledError):
                            raise exc
            except (OSError, websockets.exceptions.ConnectionClosed) as exc:
                self.state.record_local_event(
                    request_id=self.state.session_id,
                    event="session_error",
                    status="error",
                    summary=f"{type(exc).__name__}: {exc}",
                )
                self.state.set_connected(False)
                if self._stop_evt.is_set():
                    break
                await asyncio.sleep(RECONNECT_DELAY_S)
            finally:
                self.state.record_local_event(
                    request_id=self.state.session_id,
                    event="session_disconnected",
                    status="ok",
                    summary="companion disconnected",
                )
                self.state.set_connected(False)
            if self._stop_evt.is_set():
                break

    async def _reconnect_watcher(self, ws: websockets.ClientConnection) -> None:
        assert self._reconnect_async is not None
        assert self._stop_async is not None
        reconnect_task = asyncio.create_task(self._reconnect_async.wait())
        stop_task = asyncio.create_task(self._stop_async.wait())
        done, pending = await asyncio.wait(
            [reconnect_task, stop_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            task.result()
        await ws.close()

    async def _cursor_sender(self, sender: WSSender) -> None:
        interval = 1.0 / self.cursor_send_hz
        while not self._stop_evt.is_set():
            snapshot = self.state.snapshot()
            if snapshot.local_cursor is not None:
                payload = {
                    "type": "cursor",
                    "x": snapshot.local_cursor.x,
                    "y": snapshot.local_cursor.y,
                    "source": self.cursor_source,
                    "ts": snapshot.local_cursor.ts,
                }
                msg_id = await sender.send_json("cursor", payload)
                self.state.maybe_record_cursor_sent(
                    request_id=f"cursor:{msg_id}",
                    cursor=snapshot.local_cursor,
                )
            await asyncio.sleep(interval)

    async def _client_trace_sender(self, sender: WSSender) -> None:
        while not self._stop_evt.is_set():
            payload = self._pop_next_client_trace()
            if payload is None:
                await asyncio.sleep(0.1)
                continue
            await sender.send_json("client_trace", {"type": "client_trace", **payload})

    async def _mic_sender(self, sender: WSSender) -> None:
        q: asyncio.Queue[bytes] = asyncio.Queue()
        self._mic_queue = q

        def callback(indata, frames, time_info, status) -> None:
            if status:
                return
            q.put_nowait(bytes(indata))

        with sd.RawInputStream(
            samplerate=IN_RATE,
            channels=CHANNELS_IN,
            dtype=DTYPE,
            blocksize=CHUNK_SAMPLES,
            callback=callback,
        ):
            self.state.record_local_event(
                request_id=self.state.session_id,
                event="audio_stream_started",
                status="ok",
                summary="microphone streaming started",
                agent_name="concierge",
            )
            while not self._stop_evt.is_set():
                try:
                    chunk = await asyncio.wait_for(q.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                if self.state.snapshot().muted:
                    continue
                if not self._audio_gate_open:
                    continue
                # Energy gate: suppress echo while TTS audio is still playing
                if time.monotonic() < self._tts_play_until:
                    continue  # full suppression while TTS playing; AEC handles barge-in
                chunk = self._aec.process(chunk)
                await sender.send_bytes("mic_chunk", chunk)
        self._mic_queue = None

    async def _receiver_loop(
        self,
        ws: websockets.ClientConnection,
        executor: LocalToolExecutor,
    ) -> None:
        with sd.RawOutputStream(
            samplerate=OUT_RATE,
            channels=CHANNELS_OUT,
            dtype=DTYPE,
            blocksize=0,
        ) as out:
            lat = out.latency
            self._output_latency_s = float(lat if isinstance(lat, (int, float)) else lat[1])
            print(f"[audio] output latency={self._output_latency_s*1000:.1f}ms")
            async for msg in ws:
                if isinstance(msg, bytes) and msg:
                    out.write(msg)
                    self._aec.push_speaker(msg)
                    # bytes / (samples/s * bytes/sample) = duration in seconds
                    duration_s = len(msg) / (OUT_RATE * 2)
                    self._tts_play_until = max(
                        self._tts_play_until,
                        time.monotonic() + duration_s + self._output_latency_s + TTS_TAIL_S,
                    )
                    continue
                if not isinstance(msg, str):
                    continue
                try:
                    payload = json.loads(msg)
                except Exception:
                    continue
                if payload.get("type") == "audio_gate":
                    await self._handle_audio_gate(payload)
                    continue
                if self.state.handle_server_message(payload):
                    continue
                await executor.handle_message(payload)

    async def _handle_audio_gate(self, payload: dict[str, object]) -> None:
        state = str(payload.get("state", "") or "").lower()
        reason = str(payload.get("reason", "") or "")
        if state == "closed":
            self._audio_gate_open = False
            self._drain_mic_queue()
            self.state.record_local_event(
                request_id=self.state.session_id,
                event="audio_gate_closed",
                status="ok",
                summary=f"audio gate closed ({reason})",
            )
            return
        if state == "open":
            self._audio_gate_open = True
            self.state.record_local_event(
                request_id=self.state.session_id,
                event="audio_gate_opened",
                status="ok",
                summary=f"audio gate opened ({reason})",
            )

    def _drain_mic_queue(self) -> None:
        q = self._mic_queue
        if q is None:
            return
        while True:
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                return

    def _executor_event_callback(self, payload: dict[str, object]) -> None:
        calibration_state = str(payload["calibration_state"]) if payload.get("calibration_state") else None
        if calibration_state is not None:
            self.state.set_calibration_state(calibration_state, str(payload.get("summary", "")))

    def _queue_client_trace(self, payload: dict[str, object]) -> None:
        if str(payload.get("source")) != "client":
            return
        if str(payload.get("event")) not in CLIENT_TRACE_EVENTS:
            return
        with self._client_trace_lock:
            self._pending_client_traces.append(dict(payload))

    def _pop_next_client_trace(self) -> Optional[dict[str, object]]:
        with self._client_trace_lock:
            if not self._pending_client_traces:
                return None
            return self._pending_client_traces.popleft()

    def _rotate_session(self) -> None:
        with self._client_trace_lock:
            self._pending_client_traces.clear()
        self.state.set_session_id(generate_session_id())
