# OmniPilot Private

OmniPilot Private extends DevPilot AI into a local-first Windows desktop agent.

## Privacy Defaults

- The agent sleeps until `Hey Chinna WakeUp`.
- While sleeping, no screenshots or transcripts are captured.
- Private data is stored in local AppData, not OneDrive-backed Desktop/Documents.
- A Desktop entry named `PavanPrivate app` points to the local vault.
- Cloud AI is disabled by default for OmniPilot Private.

## Optional Local Tools

Install the optional stack on the target Windows laptop:

```powershell
.\scripts\setup-omnipilot.ps1
```

The app works in limited mode if these tools are missing.

## Wake And Sleep

- Wake phrase: `Hey Chinna WakeUp`
- Sleep phrase: `sleep` or `go to sleep`
- Fallback: `Alt+Space` and dashboard controls
- Click **Start Wake Listener** to run the local microphone listener. It only processes commands after the wake phrase when sleeping.
- Click **Talk** for push-to-talk voice commands. OmniPilot transcribes locally with Whisper and speaks replies with local/browser TTS.

## Screen Perception And Action

- Observation captures a local screenshot in the private vault.
- Active-window detection reports the foreground app title and bounds.
- OCR reads visible text through Tesseract when installed.
- UI Automation extracts visible controls when available.
- Natural commands include `observe my screen`, `open YouTube`, `search for agentic workflow examples`, `click login`, `click at 400 300`, `type hello`, `press ctrl l`, `scroll down`, `copy`, `paste`, and `close window`.
- Low-confidence or sensitive actions go to the approval queue before execution.

## Privacy Center

- Delete screenshots, call records, or the full vault from the dashboard.
- Export decrypted local records to a ZIP in the vault export folder.
- Raw push-to-talk audio is temporary and deleted after transcription; transcripts are stored as encrypted vault records.

## Safety

OmniPilot requires approval for uncertain clicks, deleting files, sending messages, custom voice use, PR creation, commits, pushes, installs, payments, credentials, system settings, and every call.

## Calls And Friend Voice

Friend voice requires a consent clip before use. Outgoing friend-voice messages/calls must disclose AI voice use. WhatsApp/Google Meet calls require approval and a recording announcement before local transcript/audio storage. If local voice cloning is unavailable, OmniPilot falls back to generic local TTS and keeps disclosure enabled.
