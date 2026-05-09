#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mkdir -p runtime

if ! pgrep -f "uvicorn app.main:app.*--port 8000" >/dev/null; then
  (
    cd backend
    DESKTOP_VOICE_ENABLED=false ./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
  ) > /tmp/chinna-backend.log 2>&1 &
fi

if ! pgrep -f "vite.*--host 0.0.0.0.*--port 5173" >/dev/null; then
  (
    cd frontend
    npm run dev:codespaces
  ) > /tmp/chinna-frontend.log 2>&1 &
fi

echo "Chinna Personal Agent is starting in Codespaces."
echo "Dashboard: forwarded port 5173"
echo "API: forwarded port 8000"
echo "Logs: /tmp/chinna-backend.log and /tmp/chinna-frontend.log"
