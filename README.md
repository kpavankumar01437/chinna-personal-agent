# DevPilot AI + OmniPilot Private

DevPilot AI is an autonomous multi-agent DevOps repair platform. It detects failing software, classifies incident severity, reasons through the root cause, repairs code in a sandbox, verifies the fix with tests, explains mistakes and resolutions, generates rollback notes, estimates time saved, stores incident memory, and prepares a GitHub PR.

OmniPilot Private extends DevPilot into a local-first Windows desktop operator. It wakes on `Hey Chinna WakeUp`, sleeps on `sleep`, stores private data in a local vault, observes the active screen with screenshots/OCR/UI Automation, controls the screen through supervised actions, speaks replies, and delegates code repair work to DevPilot Engineer.

The project is built for an Agentathon-style judging flow: it is a real app, but it includes a repeatable sample repository so the full autonomous loop can be shown reliably in under five minutes.

## What It Demonstrates

- **Perception:** incidents from logs, test output, local repo paths, and sample failures.
- **Reasoning:** manager-led workflow with analyzer, memory, research, fixer, tester, reviewer, guardrail, PR writer, and voice briefing agents.
- **Action:** sandboxed code edits, test execution, diff generation, PR preview or GitHub PR creation, and optional webhook notification.
- **Self-correction:** failed first attempts become mistake-resolution records and feed the next attempt.
- **Private desktop operation:** wake/sleep operator console, always-on local wake listener, push-to-talk voice commands, spoken replies, local vault, OCR screen observation while awake, sensitive-action approvals, friend-voice consent records, and supervised call/message workflows.

## Tech Stack

- Frontend: React + Vite
- Desktop shell: Electron + electron-builder
- Backend: FastAPI
- Agent workflow: deterministic LangGraph-style state machine with OpenAI-compatible model hooks
- Storage: SQLite
- AI routing defaults:
  - `gpt-5.5` for reasoning-heavy agents
  - `gpt-5.1-codex-max` for code repair

## Quick Start

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open the frontend URL shown by Vite, usually `http://localhost:5173`.

### Desktop App

```powershell
cd frontend
npm install
npm run desktop
```

The desktop app includes a tray icon and floating mini companion. `Alt+Space` opens the mini panel from anywhere.

Build the Windows installer:

```powershell
cd frontend
npm run dist
```

The installer output is created under `frontend/release/`.

Create a direct desktop shortcut to the packaged desktop app:

```powershell
.\scripts\create-desktop-shortcut.ps1
```

Enable launch on Windows startup:

```powershell
.\scripts\enable-omnipilot-startup.ps1
```

### OmniPilot Optional Local Stack

```powershell
.\scripts\setup-omnipilot.ps1
```

This installs optional local tools for the private voice/screen agent: Ollama, Qwen models, FFmpeg, Tesseract OCR, Whisper dependencies, PyAutoGUI, UI Automation, and local TTS. If a download fails, the app still works in limited mode.

## Environment

Copy `.env.example` to `.env` or set these variables directly:

```text
OPENAI_API_KEY=
OPENAI_REASONING_MODEL=gpt-5.5
OPENAI_CODING_MODEL=gpt-5.1-codex-max
GITHUB_TOKEN=
GITHUB_OWNER=
GITHUB_REPO=
GITHUB_BASE_BRANCH=main
DISCORD_WEBHOOK_URL=
```

The app still runs without API keys. In that mode, it uses deterministic local agent behavior and generates a PR draft preview instead of creating a real PR.

## Judging Flow

1. Start backend and frontend.
2. In OmniPilot Console, click **Start Wake Listener** or **Talk**.
3. Say or type `Hey Chinna WakeUp observe my screen`.
4. Say or type `run DevPilot repair demo`.
5. Watch the timeline, mistake tracker, diff, tests, security review, rollback plan, memory entry, and voice briefing.
6. Open the PR approval panel and generate the PR preview.

## Repository Layout

```text
backend/      FastAPI app, SQLite persistence, agent workflow, tests
frontend/     React operational dashboard
sample-repo/  Intentionally buggy Python project used by DevPilot
docs/         Architecture and judging script
scripts/      Local setup helpers for OmniPilot
```

## OmniPilot Private

Key defaults:

- Wake phrase: `Hey Chinna WakeUp`
- Sleep phrase: `sleep`
- Fallback hotkey: `Alt+Space`
- Real private vault: local AppData, not OneDrive
- Desktop entry: `PavanPrivate app`
- Cloud AI: disabled by default for OmniPilot
- Screen perception: screenshot, active window, OCR, UI Automation elements
- Screen actions: open URL/app, web search, click coordinates, click UI target, type, hotkeys, scroll, supervised command execution
- Privacy tools: delete, wipe, and export local vault

For details, see `docs/OMNIPILOT_PRIVATE.md`.

## GitHub Automation

This project includes GitHub Actions CI in `.github/workflows/ci.yml`.

On push or pull request, GitHub runs:

- Backend agent workflow tests.
- Frontend dashboard production build.

For setup details, see `docs/GITHUB_AUTOMATION.md`.
