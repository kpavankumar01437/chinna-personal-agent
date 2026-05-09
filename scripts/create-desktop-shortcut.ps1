param(
    [string]$ShortcutName = "OmniPilot Private Desktop"
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

$desktop = [Environment]::GetFolderPath("Desktop")
if (-not (Test-Path -LiteralPath $desktop)) {
    $desktop = Join-Path $HOME "Desktop"
}

$shortcutPath = Join-Path $desktop "$ShortcutName.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $exe
$shortcut.WorkingDirectory = Split-Path -Parent $exe
$shortcut.IconLocation = "$exe,0"
$shortcut.Description = "Launch OmniPilot Private desktop assistant with tray and floating mini panel."
$shortcut.Save()

Write-Host "Created desktop shortcut: $shortcutPath"
