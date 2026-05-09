$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$site = Join-Path $root "site"

if (Test-Path -LiteralPath $site) {
    Remove-Item -LiteralPath $site -Recurse -Force
}

New-Item -ItemType Directory -Path $site | Out-Null
Copy-Item -LiteralPath (Join-Path $root "index.html") -Destination (Join-Path $site "index.html")
Copy-Item -LiteralPath (Join-Path $root ".nojekyll") -Destination (Join-Path $site ".nojekyll")

Write-Host "Prepared GitHub Pages site at $site"
