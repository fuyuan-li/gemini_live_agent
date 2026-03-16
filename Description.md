# Wand — Project Description

## 1. Features and Functionality

Wand is a voice-first, pointer-aware live agent that lets users control their browser by speaking and pointing — no typing, no clicking.

**Core features:**

- **Universal browser control** — works across any daily-use website: maps, video streaming, online shopping, news, and general browsing. The agent can interact with any webpage element — media
  players, images, buttons, text fields, and figures — through natural voice commands.
- **Voice control** — speak naturally to navigate, search, scroll, zoom, click, and go back. The agent understands intent and acts immediately.
- **Hand pointer ("here" actions)** — a webcam tracks the user's index finger via MediaPipe. Saying "click here", "scroll here", or "zoom in here" acts on whatever the user is physically pointing at  
  on screen.
- **Visual understanding** — saying "what is this?" triggers an on-demand screenshot annotated with the cursor position, which is injected into the agent's context so it can describe what the user is
  pointing at.
- **Live and factual Q&A** — answers questions about what the user is currently seeing on screen, as well as general factual and real-time queries ("who made this?", "what's the weather?") via Google
  Search — without opening a new tab.
- **Multi-agent routing** — a root concierge agent routes intent to a browser specialist or search specialist transparently, with no user-visible handoff.
- **Barge-in** — the user can interrupt the agent mid-response by speaking; ongoing audio playback is cleared immediately.
- **Auto-recovery** — on any session crash or disconnect, the client automatically reconnects within 2 seconds and resumes operation.
- **Hand calibration** — a guided 4-point calibration maps finger position to screen coordinates, supporting accurate pointer actions across different camera angles and screen sizes.

---

## 2. Technologies Used

**AI & Agent Framework**

- **Google ADK (Agent Development Kit)** — multi-agent orchestration, `LiveRequestQueue` for bidirectional audio streaming, `AgentTool` for wrapping agents as callable tools, built-in
  `transfer_to_agent` for agent handoffs
- **Gemini 2.5 Flash Native Audio** (via Gemini Live API) — real-time bidirectional audio for the concierge and browser_agent; processes voice input and generates spoken responses with sub-second
  latency
- **Gemini 2.5 Flash** — powers the search_agent for text-based web search queries
- **Google Search API** — built-in ADK tool used by search_agent for grounded factual answers

**Cloud Infrastructure**

- **Google Cloud Run** — hosts the FastAPI server; handles all agent orchestration and Gemini Live sessions; scales automatically
- **Google Cloud Secret Manager** — stores the Gemini API key securely; injected into Cloud Run at deploy time via `--set-secrets`
- **Infrastructure-as-Code** — `deploy.sh` automates the full deployment pipeline: enabling GCP APIs, verifying secrets, building and deploying to Cloud Run in a single command

**Backend**

- Python 3.12, FastAPI, WebSockets — real-time bidirectional communication between cloud server and local client

**Client**

- **Playwright + Chromium** — embedded headless browser; executes all navigation, click, scroll, and drag actions locally
- **MediaPipe** — hand landmark detection; tracks index fingertip at ~20Hz via webcam
- **sounddevice** — low-latency PCM16 audio capture (16kHz) and playback (24kHz)
- **OpenCV** — webcam frame capture and cursor overlay rendering
- **pyobjc (Cocoa/Quartz)** — macOS native window, screen geometry, and display coordinate mapping

---

## 3. Findings and Learnings

**Found: a working architecture for split-deployment live agents** — deploying the agent on cloud while keeping physical device interactions local introduces a class of problems that don't exist in  
 single-machine setups: barge-in coordination across a network boundary, the agent having no view of the user's screen, cursor state living on the client while decisions are made on the server, and
session crashes requiring transparent recovery. We designed and implemented concrete solutions for each: a client-side playback guard for barge-in, on-demand screenshot injection into the Gemini audio
stream for visual context, client-side cursor resolution at execution time, and an automatic reconnection loop with session rotation.

**Found: audio gate as a pattern for robust multi-agent Live API workflows** — agent-to-agent transfers in Gemini Live are destabilized by buffered audio arriving at the new agent's session out of  
 context. We found that gating the microphone stream during handoffs — flushing the backlog before the new agent takes over — reliably prevents this. The audio gate pattern is reusable for any
multi-agent Live API system that uses ADK's `transfer_to_agent`.

**Learned: agentic topology shapes how ownership is handed off** — building with ADK revealed three distinct patterns: sub-agent (full ownership transfer, context switches), AgentTool (agent called  
 like a function, control returns to caller), and direct tool (no agent, just execution). Choosing the wrong topology causes subtle bugs — for example, using a sub-agent when you need the result
returned to the caller, or using AgentTool when you need the new agent to own the conversation. Matching topology to ownership intent is a core design decision.

**Learned: prompt boundary clarity directly improves multi-agent team performance** — ambiguous instructions produce consistent misbehavior across the whole agent team. Explicitly enumerating what  
 each agent does and does not handle — including edge cases like "play this video" (click) vs "pause" (toggle) and exact URL templates for search — reduced misrouting significantly. Clear domain
boundaries in instructions are as important as the agent topology itself.

**Learned: AEC remains an open problem for us in a barge-in system** — muting the mic during agent speech would eliminate echo but disables barge-in. We tried two approaches: AEC (speexdsp) requires  
precise latency alignment between the reference signal and mic input — small drift leaves audible residual echo. RMS-based gating detects when the speaker is active but cannot reliably distinguish  
echo amplitude from soft user speech, causing false suppression. Neither solution worked well enough without compromising barge-in responsiveness. We currently use headphones as a physical-layer  
workaround, but consider this an unsolved problem worth revisiting.
