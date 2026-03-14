#!/bin/bash
# Double-click this file in Finder to launch the Live Agent Companion app.
# On first run, macOS will ask for Camera and Microphone access — click Allow.

set -e

# Change to the repo directory regardless of where the file is located
cd "$(dirname "$0")"

# ── One-time setup ───────────────────────────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo "Setting up Python environment (one-time, ~2 min)..."
    python3 -m venv .venv
    .venv/bin/pip install -q -r requirements.txt
    .venv/bin/python -m playwright install chromium
fi

source .venv/bin/activate

# ── Launch ───────────────────────────────────────────────────────────────────
# --ws-url  Base WebSocket URL (no user-id — it's appended automatically from
#           your machine's hostname, persisted in ~/.config/companion-agent/user_id)
echo "Starting Live Agent Companion..."
python -m client.companion_app \
    --ws-url "wss://adk-agent-orchestrator-385929302643.us-central1.run.app/ws"
