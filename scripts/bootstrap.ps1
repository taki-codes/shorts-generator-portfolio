param([switch]$InstallTools, [switch]$InstallCodex, [switch]$YouTube)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
}
function Install-PackageId([string]$Id) {
    & winget.exe show --id $Id --exact --source winget
    if ($LASTEXITCODE -ne 0) { throw "Package not found: $Id. Use the official download links in README.md." }
    & winget.exe install --id $Id --exact --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "Installation failed: $Id. Restart PowerShell and check the package state." }
}

$RuntimeCheck = Join-Path $PSScriptRoot 'check_runtime.py'
function Get-CompatiblePython {
    # py -3 may prefer a free-threaded build. Select explicit regular versions.
    foreach ($Candidate in @('-3.13', '-3.12', '-3.11')) {
        try {
            $CheckOutput = & py.exe $Candidate $RuntimeCheck 2>$null
            if ($LASTEXITCODE -eq 0) {
                $RuntimeInfo = ($CheckOutput -join "`n") | ConvertFrom-Json
                if ($RuntimeInfo.compatible) {
                    return [PSCustomObject]@{ Selector = $Candidate; Info = $RuntimeInfo }
                }
            }
        } catch {
            # A selector may be missing; continue to the next explicit version.
        }
    }
    return $null
}

if ($InstallTools) {
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) { throw 'winget missing. Install Microsoft App Installer, or follow manual steps in README.md.' }
    if (-not (Get-Command py.exe -ErrorAction SilentlyContinue)) { Install-PackageId 'Python.Python.3.13' }
    if (-not (Get-Command ffmpeg.exe -ErrorAction SilentlyContinue)) { Install-PackageId 'Gyan.FFmpeg' }
    Refresh-Path
}
if ($InstallCodex) {
    if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
        if (-not $InstallTools) { throw 'Node.js/npm missing. Run with -InstallTools -InstallCodex or install Node.js LTS.' }
        Install-PackageId 'OpenJS.NodeJS.LTS'
        Refresh-Path
    }
    & npm.cmd install --global '@openai/codex'
    if ($LASTEXITCODE -ne 0) { throw 'Codex install failed.' }
    Refresh-Path
}

if (-not (Get-Command py.exe -ErrorAction SilentlyContinue)) { throw 'Python Launcher missing. Install standard 64-bit Python 3.13.' }
$SelectedPython = Get-CompatiblePython
if (-not $SelectedPython -and $InstallTools) {
    Install-PackageId 'Python.Python.3.13'
    Refresh-Path
    $SelectedPython = Get-CompatiblePython
}
if (-not $SelectedPython) { throw 'No compatible regular 64-bit Python 3.11-3.13 found. Run py -0p and install the standard Python 3.13 binary. Free-threaded builds are not supported.' }
Write-Host ("Selected regular Python: " + $SelectedPython.Info.executable)

if (Test-Path '.venv') {
    $ExistingCompatible = $false
    if (Test-Path '.venv\Scripts\python.exe') {
        try {
            $ExistingCheck = & .\.venv\Scripts\python.exe $RuntimeCheck 2>$null
            if ($LASTEXITCODE -eq 0) { $ExistingCompatible = $true }
        } catch {
            $ExistingCompatible = $false
        }
    }
    if (-not $ExistingCompatible) {
        $BackupName = '.venv-incompatible-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
        Rename-Item -LiteralPath '.venv' -NewName $BackupName
        Write-Host ("Incompatible virtual environment preserved as " + $BackupName)
    }
}
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    & py.exe $SelectedPython.Selector -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'venv creation failed.' }
}
& .\.venv\Scripts\python.exe $RuntimeCheck
if ($LASTEXITCODE -ne 0) { throw 'Virtual environment is not using a supported regular Python binary.' }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip install failed.' }
$PackageSpec = if ($YouTube) { '.[youtube]' } else { '.' }
& .\.venv\Scripts\python.exe -m pip install --only-binary=:all: --editable $PackageSpec
if ($LASTEXITCODE -ne 0) { throw 'Package installation failed.' }
& .\.venv\Scripts\python.exe -m owshort.cli doctor --out diagnostics.json
if ($LASTEXITCODE -ne 0) { throw 'Diagnostics failed.' }
Write-Host 'Setup script finished. Check diagnostics.json; VOICEVOX and Premiere are installed separately.'
