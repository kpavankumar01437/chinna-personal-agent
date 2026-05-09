param(
    [switch]$SkipModels
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"

Write-Host "Setting up OmniPilot Private local tools..."

function Get-OllamaPath {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
        "$env:ProgramFiles\Ollama\ollama.exe",
        "$env:LOCALAPPDATA\Ollama\ollama.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    return $null
}

function Add-UserPathIfMissing {
    param([string]$PathToAdd)
    if (-not $PathToAdd -or -not (Test-Path -LiteralPath $PathToAdd)) {
        return
    }
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (($userPath -split ";") -notcontains $PathToAdd) {
        [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";" + $PathToAdd), "User")
        Write-Host "Added $PathToAdd to the user PATH. Open a new PowerShell window to use it directly."
    }
}

function Get-TesseractPath {
    $cmd = Get-Command tesseract -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    $candidates = @(
        "$env:ProgramFiles\Tesseract-OCR\tesseract.exe",
        "${env:ProgramFiles(x86)}\Tesseract-OCR\tesseract.exe",
        "$env:LOCALAPPDATA\Programs\Tesseract-OCR\tesseract.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    return $null
}

if (-not (Test-Path (Join-Path $backend ".venv"))) {
    python -m venv (Join-Path $backend ".venv")
}

& (Join-Path $backend ".venv\Scripts\python.exe") -m pip install --upgrade pip
& (Join-Path $backend ".venv\Scripts\pip.exe") install -r (Join-Path $backend "requirements-omnipilot.txt")

if (Get-Command winget -ErrorAction SilentlyContinue) {
    winget install --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
    winget install --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
    winget install --id UB-Mannheim.TesseractOCR --accept-package-agreements --accept-source-agreements
} else {
    Write-Host "winget not found. Install Ollama, FFmpeg, and Tesseract OCR manually."
}

$ollamaPath = Get-OllamaPath
if ($ollamaPath) {
    $ollamaDir = Split-Path -Parent $ollamaPath
    Add-UserPathIfMissing $ollamaDir
}

$tesseractPath = Get-TesseractPath
if ($tesseractPath) {
    Add-UserPathIfMissing (Split-Path -Parent $tesseractPath)
}

if (-not $SkipModels -and $ollamaPath) {
    & $ollamaPath pull qwen3:8b
    & $ollamaPath pull qwen3:4b
} else {
    Write-Host "Skipping Ollama model downloads. OmniPilot will run in limited mode until models are installed."
}

Write-Host "OmniPilot setup completed. Some tools may require restarting the terminal or Windows."
