param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$python = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    python -m venv (Join-Path $backend ".venv")
}

if (-not $SkipInstall) {
    & $python -m pip install --upgrade pip
    & (Join-Path $backend ".venv\Scripts\pip.exe") install -r (Join-Path $backend "requirements.txt")
    Push-Location $frontend
    npm install
    Pop-Location
}

$backendCommand = "cd `"$backend`"; `$env:DESKTOP_VOICE_ENABLED='false'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
$frontendCommand = "cd `"$frontend`"; npm run dev"

Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCommand -WindowStyle Normal
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCommand -WindowStyle Normal
Start-Sleep -Seconds 3
Start-Process "http://127.0.0.1:5173"

Write-Host "Chinna web dashboard is starting at http://127.0.0.1:5173"
Write-Host "FastAPI backend is starting at http://127.0.0.1:8000"
Write-Host "For full desktop wake/screen control, run: cd frontend; npm run desktop"
