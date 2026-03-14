#!/bin/bash
# Double-click this file in Finder to launch the Live Agent Companion app.
# On first run, macOS may ask for camera / microphone permission — click Allow.

set -e

# Change to the repo directory (works wherever the file is placed)
cd "$(dirname "$0")"

# ── Setup check ─────────────────────────────────────────────────────────────
if [ ! -d ".venv" ]; then
  echo "Setting up Python environment (one-time setup, ~1 min)..."
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -q -r requirements.txt
  python -m playwright install chromium
else
  source .venv/bin/activate
fi

# ── Config ───────────────────────────────────────────────────────────────────
# Edit WS_URL below to point at your Cloud Run deployment.
WS_URL="wss://adk-agent-orchestrator-385929302643.us-central1.run.app/ws/local_user"

# ── Launch ───────────────────────────────────────────────────────────────────
echo "Starting Live Agent Companion..."
python -m client.companion_app \
  --ws-url "$WS_URL" \
  --hand-overlay \
  --hand-mirror
