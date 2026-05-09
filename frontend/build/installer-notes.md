# OmniPilot Private Installer Notes

The Electron installer is configured through `electron-builder` in `package.json`.

Target:

- Windows NSIS installer
- Per-user install by default
- Optional startup shortcut
- FastAPI backend runs as local sidecar
- Backend virtual environment is packaged as an Electron extra resource for a working local sidecar on the target laptop
- Tray icon keeps OmniPilot present after closing the main console
- Floating always-on-top mini panel gives desktop controls for wake listener, wake/sleep, observe, emergency stop, and console launch
- `Alt+Space` opens the mini desktop panel from anywhere

Local AI tools are installed through `scripts/setup-omnipilot.ps1`. The setup script installs or configures Ollama, Qwen models, FFmpeg, Tesseract OCR, Whisper dependencies, PyAutoGUI, UI Automation, and local TTS. If a dependency fails, OmniPilot continues in limited mode and reports the missing capability in the dashboard.
