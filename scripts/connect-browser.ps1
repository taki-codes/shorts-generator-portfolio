param([ValidateSet('msedge','chrome')][string]$Browser = 'msedge')
$ErrorActionPreference = 'Stop'
$CodexCommand = Get-Command codex.cmd -ErrorAction SilentlyContinue
if (-not $CodexCommand) { $CodexCommand = Get-Command codex.exe -ErrorAction Stop }
if (-not (Get-Command npx.cmd -ErrorAction SilentlyContinue)) { throw 'Node.js/npm must be installed first.' }
$BrowserProfile = Join-Path $env:LOCALAPPDATA 'OWShortKit\browser-profile'
# This changes Codex MCP configuration only. No website is opened or uploaded to.
& $CodexCommand.Source mcp add owshort-browser -- npx.cmd -y '@playwright/mcp@latest' --browser $Browser --user-data-dir $BrowserProfile
if ($LASTEXITCODE -ne 0) { throw 'MCP setup failed. See docs/browser.md for manual configuration.' }
Write-Host 'Browser MCP configured. Restart Codex and check /mcp before uploading.'
