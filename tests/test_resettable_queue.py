from google.adk.agents.live_request_queue import LiveRequest
from google.genai import types

from app.live.resettable_queue import ResettableLiveRequestQueue


def test_drop_realtime_backlog_keeps_content_and_close_requests() -> None:
    queue = ResettableLiveRequestQueue()
    queue.send_realtime(types.Blob(mime_type="audio/pcm;rate=16000", data=b"123"))
    queue.send(LiveRequest(activity_start=types.ActivityStart()))
    queue.send_content(types.Content(role="user", parts=[types.Part(text="quit")]))
    queue.send(LiveRequest(close=True))

    dropped = queue.drop_realtime_backlog()

    assert dropped == 2

    first = queue._queue.get_nowait()
    second = queue._queue.get_nowait()

    assert first.content is not None
    assert second.close is True
