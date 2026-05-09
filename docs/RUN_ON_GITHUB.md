# Run Chinna Personal Agent On GitHub

GitHub Pages is static hosting, so it can only show the public project page. The working GitHub-hosted app should be run in GitHub Codespaces.

## Start In Codespaces

1. Open: https://codespaces.new/kpavankumar01437/chinna-personal-agent?quickstart=1
2. Wait for the dev container setup to finish.
3. Open the forwarded `5173` port named `Chinna Dashboard`.
4. The dashboard automatically connects to the forwarded backend on port `8000`.

The dev container automatically runs:

```bash
backend/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
npm run dev:codespaces
```

## What Works In Codespaces

- React dashboard.
- FastAPI backend.
- Incident intake.
- DevPilot sample repair workflow.
- Timeline, mistakes, tests, rollback, memory, and PR preview.
- GitHub Actions CI and Pages deployment.

## What Requires The Local Windows App

- Electron tray app.
- Floating desktop mini panel.
- Global wake phrase from anywhere on Windows.
- Local microphone listener.
- Local pyttsx3 voice output.
- OCR of your real screen.
- PyAutoGUI and Windows UI Automation screen control.
- Local private vault in AppData.
- Ollama running on your laptop.

This split is required by browser and GitHub security rules. GitHub-hosted code cannot take control of a user's private desktop.

## Download The Desktop Build From GitHub

Use the latest release page for the Windows installer:

https://github.com/kpavankumar01437/chinna-personal-agent/releases/latest

If no release asset is present yet, open GitHub Actions and run `Build Windows Installer`. The workflow publishes a downloadable installer artifact.
