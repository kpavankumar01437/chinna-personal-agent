param(
    [string]$ShortcutName = "OmniPilot Private"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$appDir = Join-Path $root "frontend\release\win-unpacked"
$exeCandidates = @(
    (Join-Path $appDir "Chinna Personal Agent.exe"),
    (Join-Path $appDir "OmniPilot Private.exe")
)
$exe = $exeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (-not $exe) {
    throw "Desktop app executable was not found. Build it first with: cd frontend; npm run dist"
}

$startup = [Environment]::GetFolderPath("Startup")
if (-not (Test-Path -LiteralPath $startup)) {
    throw "Windows Startup folder was not found."
}

$shortcutPath = Join-Path $startup "$ShortcutName.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $exe
$shortcut.WorkingDirectory = Split-Path -Parent $exe
$shortcut.IconLocation = "$exe,0"
$shortcut.Description = "Start OmniPilot Private desktop assistant when Windows starts."
$shortcut.Save()

Write-Host "Created startup shortcut: $shortcutPath"
