# Wand

A new way to interact with the web — a live AI agent that sees, talks, and acts in real time as you speak and point at your screen. No typing. No mouse.

**Works for:** hands-busy situations (cooking, presenting), accessibility (elderly users, limited hand mobility), and tasks where pointing is faster than describing (shopping, research).

> **macOS only.** Requires Python 3.11+, a webcam, and a microphone.
> **Recommended: use headphone** Otherwise there will be echo loops, which is an known issue from community discussion over ADK.

---

## For Judges

macOS only. Python 3.11+, webcam, microphone required.

**Step 1 — Install client** (one command, ~2–3 min):

```bash
curl -fsSL https://raw.githubusercontent.com/fuyuan-li/gemini_live_agent/main/install.sh | bash
```

**Step 2 — Run:**

```bash
wand
```

The app connects automatically to the live backend on Google Cloud Run.
No API keys or configuration needed.

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
4. Add a `wand` command to your PATH

**First-time duration:** about 2–3 minutes (mostly the Chromium download).

### Start the app

```bash
wand
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

| Problem                   | Fix                                                                            |
| ------------------------- | ------------------------------------------------------------------------------ |
| `wand: command not found` | Open a new terminal or run `source ~/.zshrc`                                   |
| Camera / mic not working  | System Settings → Privacy & Security → Camera/Microphone → enable Terminal     |
| Stuck on "Connecting…"    | Check internet connection; backend runs on Google Cloud Run                    |
| Broken after an update    | Delete `~/.local/share/companion-agent/.venv`, then re-run the install command |

---

## How it works

| What you do                    | What happens                                         |
| ------------------------------ | ---------------------------------------------------- |
| Speak naturally                | Gemini Live transcribes and routes your request      |
| Say "open Google Maps"         | The embedded browser navigates automatically         |
| Point your finger at something | The app tracks your hand via webcam                  |
| Say "click here"               | The AI clicks where your finger is pointing          |
| Say "what is this?"            | The AI takes a screenshot and describes what it sees |

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

A `deploy.sh` script automates the full deployment:

```bash
./deploy.sh                   # uses your gcloud default project
./deploy.sh my-project-id     # explicit project
```

The script enables all required GCP APIs, verifies that `GOOGLE_API_KEY` exists in Secret Manager, builds a container from source, and deploys to Cloud Run — injecting the key securely via `--set-secrets` (never hardcoded).

**Prerequisite:** store your Gemini API key in Secret Manager once:

```bash
gcloud secrets create GOOGLE_API_KEY --data-file=- <<< "YOUR_KEY"
```

---

## Architecture

The server (Google Cloud Run) handles all agent orchestration and AI inference. The local client owns the microphone, speaker, webcam, and the embedded Playwright browser. Browser actions are forwarded over WebSocket as `tool_call` / `tool_result` messages.

```
Cloud Run (server)                    Local machine (client)
──────────────────                    ──────────────────────
FastAPI + Google ADK                  companion_app (wand)
Gemini Live API (BIDI streaming)  ←→  mic / speaker / webcam
concierge → browser_agent            Playwright browser
                                      hand tracking (MediaPipe)
```
