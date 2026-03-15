# Technical Lessons Learned

Debugging session: YouTube audio in headless Playwright + agent behavior tuning.

---

## 1. Headless Chromium Has No Audio Output (Root Cause, Never Fully Solved)

`companion_app` runs the browser in headless mode with CDP screencasting — the browser renders frames that get displayed inside the macOS app window.

Headless Chromium uses a **null audio sink**: the audio pipeline runs and decodes video correctly, but the output PCM is discarded instead of being sent to CoreAudio.

The JS-level state while a video is playing looks completely normal:
```
muted: False, volume: 1, paused: False, readyState: 4, currentTime: 14.17
```
The browser "thinks" it's playing audio. No amount of JS unmuting fixes anything — the problem is below JS.

`channel='chrome'` (system-installed Chrome) also doesn't help — headless null sink behavior is the same.

**Options if you need audio:**
- Run non-headless (a real browser window appears alongside the app)
- Capture audio at the JS layer via Web Audio API + stream PCM to Python (see lesson 2 for the blocker)

---

## 2. Chrome PNA Blocks ws://localhost from HTTPS Pages

Attempted approach: inject JS to capture video audio via `MediaElementAudioSourceNode` + `ScriptProcessorNode`, stream Float32 PCM chunks over WebSocket to a local Python server, play via `sounddevice`.

Blocked by Chrome's **Private Network Access (PNA)** policy: pages at a public HTTPS origin (e.g. `youtube.com`) cannot connect to private network endpoints (`ws://localhost`) without a PNA preflight request. The Python `websockets` server doesn't handle HTTP preflights → browser silently drops the connection (no error visible in Python logs).

**Fix flag** (add to Chromium launch args):
```
--disable-features=PrivateNetworkAccessSendPreflights,PrivateNetworkAccessRespectPreflightResults
```

**Lesson**: Any JS-to-localhost WebSocket initiated from an HTTPS page requires disabling PNA in the Chromium launch args, or the Python server must handle the OPTIONS preflight.

---

## 3. Diagnose Before Fixing — Don't Guess

Two early fixes were based on wrong assumptions (autoplay policy flag, JS unmute after navigate). Neither worked because the problem was never what we assumed.

Real diagnosis: added structured `[audio_debug]` print statements at 5 time points in `navigate()` and at the moment of `play_pause()`:

```
[audio_debug] after domcontentloaded: {'video': None, 'audioContext': 'running'}
[audio_debug] after 500ms: {'muted': False, 'volume': 1, 'paused': True, 'readyState': 0}
...
[audio_debug] play_pause: before={'muted': False, 'volume': 1, 'paused': False, 'readyState': 4, 'currentTime': 14.17}
```

This eliminated muting as a cause in one test run. Everything pointed to OS/process level.

**Lesson**: Before writing any fix, add diagnostic logging to get real runtime state. The actual data will either confirm your hypothesis or immediately rule it out.

---

## 4. Architecture: What Runs Where (Redeploy or Not)

| File | Runs on | Redeploy needed? |
|---|---|---|
| `app/agents/browser_agent.py` | Server (Cloud Run) | Yes |
| `app/agents/concierge.py` | Server | Yes |
| `app/tools/remote_browser.py` | Server | Yes |
| `app/runtime/browser_runtime.py` | Client | No |
| `app/tools/browser/navigation.py` | Client (via local_executor) | No |
| `app/tools/browser/media.py` | Client | No |
| `client/local_executor.py` | Client | No |
| `client/companion_runtime.py` | Client | No |

The browser tool call flow: Server agent → WebSocket `tool_call` → `local_executor.py` → Playwright → WebSocket `tool_result` → Server.

**Lesson**: Always check which side a file runs on before deciding whether a redeploy is needed.

---

## 5. YouTube Homepage ≠ A Playing Video

`youtube.com` homepage has a video element in the DOM but it has `readyState: 0, paused: True` — it's a background/preview element, not an actual video playing.

Diagnosing audio on the homepage is useless. You need to:
1. Click into a specific video
2. Let it start playing
3. Then capture diagnostic state

**Lesson**: Always test with the actual scenario you're debugging (video playing), not the landing page.

---

## 6. Multi-Output Device + Headless = Silent

The system audio setup: Multi-Output Device = BlackHole 2ch + AirPods.

- Agent TTS works: Python `sounddevice` → system default (Multi-Output Device) → AirPods ✓
- Browser audio silent: headless Chromium never connects to CoreAudio at all

System audio routing is completely irrelevant if the process never initializes a CoreAudio output session.

**Lesson**: Confirm that the process itself is connecting to an audio device before debugging routing.

---

## 7. Agent: "Play This Video" Triggered play_pause Instead of click_here

When the user pointed at a YouTube thumbnail and said "play this video", the agent called `remote_play_pause()` instead of `remote_click_here()`. The word "play" matched the play/pause rule.

**Fix in instruction**: `remote_play_pause()` is ONLY for toggling a video that is already open and playing/paused. Pointing at a thumbnail + saying "play this" / "open this" / "this is cool" = `remote_click_here()`.

---

## 8. Agent: "Cannot Type in Search Bar" Error

The agent tried to click search bars and type text instead of constructing a URL with query parameters, then reported it couldn't do it.

**Fix**: Always give the agent explicit URL templates for every search action in the demo:
```
YouTube: https://www.youtube.com/results?search_query={terms}
Amazon:  https://www.amazon.com/s?k={terms}
Maps:    https://www.google.com/maps/search/{place}+near+me
```

**Lesson**: For demos with predictable navigation patterns, enumerate exact URL templates in the instruction. Don't let the agent figure out how to search — tell it.

---

## 9. Session Crashes: APIError 1007

Recurring error: `APIError status=None 1007 None. Request contains an invalid argument.` The session disconnects and reconnects automatically, but conversation context is lost.

Trigger pattern: often happens after agent transfers (`transfer_to_agent`) or after several turns of back-and-forth. Not fully diagnosed — likely Gemini Live API rate limit, accumulated context size, or an invalid audio frame being sent.

`companion_app` auto-reconnects, but the new session starts fresh with no memory of the previous conversation.

**Lesson**: Keep demo sessions short. Avoid long multi-turn conversations. Restart the app between demo runs.

---

## 10. voice_cli.py vs companion_app.py Are Not Interchangeable

- `voice_cli.py` defaults to `ws://localhost:8000` and reconnects in a loop if not reachable
- With `--ws-url` pointing to the cloud server, it returns HTTP 403 (handshake or auth difference)
- `companion_app.py` with `--ws-url` works fine against the cloud server

The two clients build WebSocket URLs differently and likely use different session ID formats that the cloud server validates differently.

**Lesson**: For testing against the cloud deployment, only use `companion_app.py`. Don't assume `voice_cli.py` is a drop-in alternative.
