# gemini_live_agent

A voice-first Gemini ADK agent with Playwright browser tools and pointer-aware "here" actions.

## Runtime Split

The project now supports a cloud-orchestrated runtime:

- Cloud Run hosts the FastAPI + ADK orchestrator.
- The local client still owns mic/speaker, cursor tracking, and the visible Playwright browser.
- Browser actions are forwarded over the existing WebSocket as `tool_call` / `tool_result` JSON messages.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Set env vars:

```bash
export GOOGLE_API_KEY="YOUR_API_KEY"
```

## Run Server

```bash
uvicorn app.server:app --host 127.0.0.1 --port 8000
```

For local client development, keep using `requirements.txt`.

For Cloud Run builds, use the dedicated server dependency set in `requirements-cloud.txt`.

Example deploy:

```bash
gcloud run deploy adk-agent-orchestrator \
  --source . \
  --region us-central1 \
  --allow-unauthenticated
```

Set `GOOGLE_API_KEY` in the Cloud Run service configuration before invoking the orchestrator remotely.

## Phase 1: Standalone Webcam Cursor (no voice required)

Run standalone cursor debug tool first to validate camera, mapping, and UI:

```bash
python -m client.cursor_debug --camera-index 0 --overlay --preview
```

The tracker uses MediaPipe Tasks API and a `hand_landmarker.task` model.
It uses the bundled read-only model at:

`client/models/hand_landmarker.task`

Controls:

- `o` / `toggle_overlay`: toggle cursor overlay visibility
- `c` / `calibrate`: run guided 4-point calibration
- `clear_calibration`: clear active in-memory calibration
- `q`: quit

Calibration notes:

- Calibration is optional and off by default until you run `c` / `calibrate`.
- Calibration stays in the current client process only; it is not written to disk.

Notes:

- Overlay dot is a virtual cursor marker (does not move OS mouse).
- Overlay currently uses a native macOS implementation (no cv2 fallback).
- Preview window is optional and rendered as a small bottom-right window.

## Phase 1 Integration: Voice Client + Cursor Stream

By default, `voice_cli` uses hand cursor provider and sends cursor over WS.

```bash
python client/voice_cli.py --cursor-source hand --camera-index 0 --hand-overlay --hand-preview
```

Use mouse fallback mode:

```bash
python client/voice_cli.py --cursor-source mouse
```

Useful options:

- `--cursor-send-hz 20`
- `--cursor-stale-ms 400`
- `--hand-smoothing 0.35`
- `--hand-overlay-radius 10`

## Agent Topology

Current topology:

- `concierge` -> `browser_agent`

Responsibilities:

- `concierge`: handles top-level voice interaction and delegates browser requests.
- `browser_agent`: runs in the orchestrator and forwards browser actions to the local executor (`navigate`, `click_here`, `scroll_here`, `drag_here`, `pan`).

## Protocol

Cursor payload supports required + optional fields:

```json
{
  "type": "cursor",
  "x": 100,
  "y": 200,
  "source": "hand",
  "confidence": 0.92,
  "ts": 1730000000.0
}
```

Server only requires `type/x/y`; optional fields are accepted for forward compatibility.

Tool bridge payloads:

```json
{
  "type": "tool_call",
  "call_id": "uuid",
  "tool": "navigate",
  "args": {
    "url": "https://maps.google.com"
  }
}
```

```json
{
  "type": "tool_result",
  "call_id": "uuid",
  "ok": true,
  "result": {
    "url": "https://maps.google.com",
    "title": "Google Maps"
  }
}
```
