# Live Agent Companion

A voice-first AI assistant with hand-gesture control and an embedded browser — powered by Google Gemini Live and ADK.

> **macOS only.** Requires Python 3.11+, a webcam, and a microphone.

---

## Install (end users)

Open Terminal and run:

```bash
curl -fsSL https://raw.githubusercontent.com/fuyuan-li/gemini_live_agent/main/install.sh | bash
```

The installer will:

1. Clone this repository to `~/.local/share/companion-agent`
2. Create a Python virtual environment and install all dependencies
3. Download the Chromium browser (~150 MB, one time only)
4. Add a `holly` command to your PATH

**First-time duration:** about 2–3 minutes (mostly the Chromium download).

### Start the app

```bash
holly
```

On first launch macOS will ask for **Camera** and **Microphone** access — click **Allow** for both.

The app connects automatically to the shared backend at:
```
wss://adk-agent-orchestrator-385929302643.us-central1.run.app/ws
```
No configuration needed — it just works.

### Update

Re-run the same install command. It will pull the latest code and skip re-downloading dependencies.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `holly: command not found` | Open a new terminal or run `source ~/.zshrc` |
| Camera / mic not working | System Settings → Privacy & Security → Camera/Microphone → enable Terminal |
| Stuck on "Connecting…" | Check internet connection; backend runs on Google Cloud Run |
| Broken after an update | Delete `~/.local/share/companion-agent/.venv`, then re-run the install command |

---

## How it works

| What you do | What happens |
|-------------|--------------|
| Speak naturally | Gemini Live transcribes and routes your request |
| Say "open Google Maps" | The embedded browser navigates automatically |
| Point your finger at something | The app tracks your hand via webcam |
| Say "click here" | The AI clicks where your finger is pointing |
| Say "what is this?" | The AI takes a screenshot and describes what it sees |

Each machine gets a stable unique user ID derived from its hostname (stored in `~/.config/companion-agent/user_id`), so multiple users can connect simultaneously without conflicts.

---

## For developers

```bash
git clone https://github.com/fuyuan-li/gemini_live_agent.git
cd gemini_live_agent

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Run (connects to Cloud Run backend)
python -m client.companion_app

# Run against a local server
uvicorn app.server:app --host 127.0.0.1 --port 8000
python -m client.companion_app --ws-url ws://127.0.0.1:8000/ws
```

Hand calibration: follow the cyan ring targets in sequence (Top-Left → Top-Right → Bottom-Right → Bottom-Left). Once calibrated, "click here" and "scroll here" track your finger accurately.

### Deploy server to Cloud Run

```bash
gcloud run deploy adk-agent-orchestrator \
  --source . \
  --region us-central1 \
  --allow-unauthenticated
```

Set `GOOGLE_API_KEY` in the Cloud Run service environment variables.

---

## Runtime Split

The project now supports a cloud-orchestrated runtime:

- Cloud Run hosts the FastAPI + ADK orchestrator.
- The local client still owns mic/speaker, cursor tracking, and the visible Playwright browser.
- Browser actions are forwarded over the existing WebSocket as `tool_call` / `tool_result` JSON messages.

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

- `concierge`: handles top-level voice interaction, owns non-browser conversation, and delegates browser requests.
- `browser_agent`: runs in the orchestrator and forwards browser actions to the local executor (`navigate`, `click_here`, `scroll_here`, `drag_here`, `pan`).

Handoff rules:

- `browser_agent` only handles browser control: opening pages/sites and interacting with the current page.
- If the user asks for something outside browser control, or the request is ambiguous, `browser_agent` transfers back to `concierge`.
- This handoff uses ADK's built-in `transfer_to_agent`; do not add `transfer_to_agent` manually to `tools=[...]` when the agent already has `sub_agents`.

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
