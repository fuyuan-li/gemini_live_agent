# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A voice-first, pointer-aware multi-agent system built on Google ADK (Agent Development Kit). It splits execution between a cloud orchestrator (FastAPI + Google ADK) and a local client (audio, hand cursor tracking, Playwright browser).

## Commands

### Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
export GOOGLE_API_KEY="YOUR_API_KEY"
```

### Run Server (local dev)
```bash
uvicorn app.server:app --host 127.0.0.1 --port 8000
```

### Run Client
```bash
# With hand cursor tracking
python client/voice_cli.py --cursor-source hand --camera-index 0 --hand-overlay --hand-preview

# With mouse fallback
python client/voice_cli.py --cursor-source mouse

# macOS companion app (demo mode)
python client/companion_app.py --ws-url wss://YOUR-CLOUD-RUN-SERVICE/ws/local_user
```

### Validate Webcam Cursor
```bash
python -m client.cursor_debug --camera-index 0 --overlay --preview
```

### Tests
```bash
pytest tests/
pytest tests/test_agent_routing.py   # single test file
```

### Type Checking
```bash
pyright
```

### Cloud Deploy
```bash
gcloud run deploy adk-agent-orchestrator --source . --region us-central1 --allow-unauthenticated
```
Cloud Run uses `requirements-cloud.txt` (excludes Playwright, audio, cursor/MediaPipe libs).

## Architecture

### Runtime Split

The server (Cloud Run) handles agent orchestration and decision-making. The local client owns the microphone/speaker, cursor tracking, and the visible Playwright browser. Browser tool calls are forwarded over WebSocket as `tool_call`/`tool_result` JSON messages.

### Multi-Agent Topology

- **`concierge`** (root) — top-level voice coordinator, delegates to sub-agents
- **`browser_agent`** — controls local browser via remote tool bridge; handles navigation, click_here, scroll_here, drag_here, pan
- **`search_agent`** — answers factual/web questions using `google_search`; can transfer to browser_agent or back to concierge

Sub-agents transfer using ADK's built-in `transfer_to_agent`. Do NOT add `transfer_to_agent` to `tools=[]` when `sub_agents` is set — ADK handles it automatically.

### Key Data Flows

**Voice → Agent:**
1. Client streams PCM16 audio → server WebSocket
2. Server-side VAD gates input, STT (`english_stt.py`) emits transcripts
3. ADK routes transcript to the appropriate agent

**Browser Action:**
1. Agent calls a `remote_*` tool (e.g., `remote_click_here`)
2. `session_bridge.py` sends `{"type": "tool_call", ...}` over WebSocket to client
3. `local_executor.py` runs the Playwright action
4. Client responds with `{"type": "tool_result", ...}`

**"Here" Pointer Actions:**
1. Client tracks hand position via MediaPipe (`webcam_tracker.py`) at ~20Hz
2. Cursor updates sent as `{"type": "cursor", "x": ..., "y": ...}` to server
3. Server caches position in `realtime_pointer.py` keyed by `(user_id, session_id)`
4. ADK callback (`callbacks/pointer.py`) injects cached cursor into tool context when agent calls click_here/scroll_here

### Key Files

| File | Role |
|------|------|
| `app/server.py` | FastAPI entry point; WebSocket session loop; audio streaming |
| `app/agents/concierge.py` | Root agent (Gemini 2.5 flash); owns sub-agents list |
| `app/agents/browser_agent.py` | Browser specialist with remote tool definitions |
| `app/agents/search_agent.py` | Search specialist using `google_search` built-in |
| `app/tools/remote_browser.py` | Translates agent tool calls → WebSocket tool_call messages |
| `app/runtime/session_bridge.py` | Sends tool_call, blocks waiting for tool_result from client |
| `app/state/realtime_pointer.py` | Global dict `{(user_id, session_id): {x, y, ts}}` |
| `app/live/english_stt.py` | Google Cloud Speech-to-Text streaming processor |
| `app/live/server_vad.py` | Voice activity detection gate |
| `app/callbacks/pointer.py` | ADK callback: injects cursor into tool context |
| `client/voice_cli.py` | CLI entry point: audio + cursor stream + tool executor loop |
| `client/local_executor.py` | Handles tool_call messages; runs Playwright actions |
| `client/cursor/webcam_tracker.py` | MediaPipe hand detection; maps finger → screen coords |
| `client/cursor/provider.py` | Protocol + impls: `MouseCursorProvider`, `HandCursorProvider` |

### Dependencies Split

- `requirements.txt` — full local dev (audio, Playwright, MediaPipe, macOS frameworks)
- `requirements-cloud.txt` — server-only (ADK, FastAPI, WebSocket, no browser/audio/cursor)

### ADK Patterns

- Agents use `google.adk.agents.LiveRequestQueue` for streaming audio
- `echo_dedupe.py` callback suppresses duplicate outputs across agent transfers
- `handoff_guard.py` callback silences audio during `transfer_to_agent` calls
- Models used: `gemini-2.5-flash` (default for agents)

### Audio Format

- Input (mic → server): PCM16, mono, 16kHz
- Output (server → speaker): PCM16, mono, 24kHz
