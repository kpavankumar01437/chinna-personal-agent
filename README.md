# DevPilot AI

DevPilot AI is an autonomous multi-agent DevOps repair platform. It detects failing software, classifies incident severity, reasons through the root cause, repairs code in a sandbox, verifies the fix with tests, explains mistakes and resolutions, generates rollback notes, estimates time saved, stores incident memory, and prepares a GitHub PR.

The project is built for an Agentathon-style judging flow: it is a real app, but it includes a repeatable sample repository so the full autonomous loop can be shown reliably in under five minutes.

## What It Demonstrates

- **Perception:** incidents from logs, test output, local repo paths, and sample failures.
- **Reasoning:** manager-led workflow with analyzer, memory, research, fixer, tester, reviewer, guardrail, PR writer, and voice briefing agents.
- **Action:** sandboxed code edits, test execution, diff generation, PR preview or GitHub PR creation, and optional webhook notification.
- **Self-correction:** failed first attempts become mistake-resolution records and feed the next attempt.

## Tech Stack

- Frontend: React + Vite
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
2. Click **Trigger Sample Incident**.
3. Click **Run Agents**.
4. Watch the timeline, mistake tracker, diff, tests, security review, rollback plan, memory entry, and voice briefing.
5. Open the PR approval panel and generate the PR preview.

## Repository Layout

```text
backend/      FastAPI app, SQLite persistence, agent workflow, tests
frontend/     React operational dashboard
sample-repo/  Intentionally buggy Python project used by DevPilot
docs/         Architecture and judging script
```

## GitHub Automation

This project includes GitHub Actions CI in `.github/workflows/ci.yml`.

On push or pull request, GitHub runs:

- Backend agent workflow tests.
- Frontend dashboard production build.

For setup details, see `docs/GITHUB_AUTOMATION.md`.
