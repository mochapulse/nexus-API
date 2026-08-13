#Requires -Version 5.1

<#
.SYNOPSIS
    Deploy the nexus-API CLI for workstation use on Windows.

.DESCRIPTION
    Creates %USERPROFILE%\.nexus-API\workstation\ with:
      .env   -- production config (DEBUG=false, safe for real power commands)
      venv\  -- isolated Python virtualenv with pinned CLI deps
      bin\   -- nexus-API.cmd shim for the permanent alias

    Adds %USERPROFILE%\.nexus-API\workstation\bin to the user PATH.
    Idempotent -- safe to run multiple times.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File cmd\deploy-cli-windows.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# -- 1. Resolve paths ------------------------------------------------
$ScriptDir  = $PSScriptRoot
$RepoRoot   = Split-Path $ScriptDir -Parent
$Workstation = Join-Path $env:USERPROFILE '.nexus-API\workstation'
$VenvDir    = Join-Path $Workstation 'venv'
$BinDir     = Join-Path $Workstation 'bin'
$EnvFile    = Join-Path $Workstation '.env'
$Requirements = Join-Path $RepoRoot 'requirements-cli.txt'
$EnvExample = Join-Path $RepoRoot 'api\.env.example'

Write-Host "Script Location: $ScriptDir"
Write-Host "Project Root:    $RepoRoot"

# -- 2. Create workstation directory ----------------------------------
Write-Host ""
Write-Host "Creating $Workstation ..."
if (-not (Test-Path $Workstation)) {
    New-Item -ItemType Directory -Path $Workstation | Out-Null
}

# -- 3. Copy .env.example to workstation/.env (force DEBUG=false) -----
if (-not (Test-Path $EnvFile)) {
    if (-not (Test-Path $EnvExample)) {
        Write-Error "$EnvExample not found - cannot create .env"
        exit 1
    }
    Copy-Item $EnvExample $EnvFile -Force
    (Get-Content $EnvFile) -replace '(?m)^DEBUG=.*', 'DEBUG=false' |
        Set-Content $EnvFile
    Write-Host "Created workstation .env (DEBUG=false)"
} else {
    (Get-Content $EnvFile) -replace '(?m)^DEBUG=.*', 'DEBUG=false' |
        Set-Content $EnvFile
    Write-Host "Workstation .env already exists (DEBUG=false enforced)"
}

# -- 4. Detect Python -------------------------------------------------
function Find-Python {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        try {
            $verOutput = & py -3 --version 2>&1
            if ($verOutput -match 'Python (\d+\.\d+)') {
                $ver = $Matches[1]
                Write-Host "Found Python $ver via py launcher"
                return 'py'
            }
        } catch {}
    }
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) {
        try {
            $verOutput = & python --version 2>&1
            if ($verOutput -match 'Python (\d+\.\d+)') {
                $ver = $Matches[1]
                Write-Host "Found Python $ver"
                return 'python'
            }
        } catch {}
    }
    return $null
}

$PyCmd = Find-Python
if (-not $PyCmd) {
    Write-Error @"
Python not found. Install Python 3.12+ from:
  winget install Python.Python.3.12
or download from https://www.python.org/downloads/
"@
    exit 1
}

# -- 5. Create virtualenv + install deps ------------------------------
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'

if (-not (Test-Path $VenvPython)) {
    Write-Host ""
    Write-Host "Creating virtualenv ..."

    # Try python directly first (more reliable than py launcher)
    $venvCreated = $false
    $pythonCmds = @(
        @{ Exe = 'python'; Args = @() },
        @{ Exe = 'py';      Args = @('-3') }
    )

    foreach ($cmd in $pythonCmds) {
        try {
            $null = & $($cmd.Exe) @($cmd.Args) -m venv --help 2>&1
            if ($LASTEXITCODE -eq 0) {
                & $($cmd.Exe) @($cmd.Args) -m venv $VenvDir 2>&1 | Out-Null
                if (Test-Path $VenvPython) {
                    $venvCreated = $true
                    break
                }
            }
        } catch {}
    }

    if (-not $venvCreated) {
        Write-Error @"
Failed to create virtualenv. Python venv module may not be available.
Try manually:
  python -m venv $VenvDir
"@
        exit 1
    }
}

Write-Host ""
Write-Host "Installing/updating dependencies ..."
& $VenvPython -m pip install --upgrade pip -q 2>&1 | Out-Null
& $VenvPython -m pip install -r $Requirements -q
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install dependencies"
    exit 1
}

# -- 6. Create nexus-API.cmd shim ------------------------------------
if (-not (Test-Path $BinDir)) {
    New-Item -ItemType Directory -Path $BinDir | Out-Null
}

$ShimPath = Join-Path $BinDir 'nexus-API.cmd'
$ShimContent = "@echo off`r`n" +
    "set `"NEXUS_DOTENV_PATH=$env:USERPROFILE\.nexus-API\workstation\.env`"`r`n" +
    "cd /d `"$RepoRoot`"`r`n" +
    "`"$VenvDir\Scripts\python.exe`" -m api.cli %*"
Set-Content -Path $ShimPath -Value $ShimContent -Encoding ASCII

Write-Host "Wrote shim: $ShimPath"

# -- 7. Add bin dir to user PATH (idempotent) ------------------------
$UserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($UserPath -notlike "*$BinDir*") {
    if ($UserPath) {
        $NewPath = "$UserPath;$BinDir"
    } else {
        $NewPath = $BinDir
    }
    [Environment]::SetEnvironmentVariable('Path', $NewPath, 'User')
    $env:Path = "$env:Path;$BinDir"
    Write-Host "Added to user PATH: $BinDir"
} else {
    Write-Host "Already in user PATH: $BinDir"
}

# -- 8. Verify -------------------------------------------------------
Write-Host ""
Write-Host "--------------------------------------"
Write-Host "  Deploy complete"
Write-Host "--------------------------------------"
Write-Host "  .env:   $EnvFile  (DEBUG=false)"
Write-Host "  venv:   $VenvDir"
Write-Host "  alias:  nexus-API"
Write-Host "  shim:   $ShimPath"
Write-Host "  shell:  User PATH"
Write-Host "--------------------------------------"
Write-Host ""
Write-Host "Open a NEW terminal, then run:"
Write-Host "  nexus-API --help"
