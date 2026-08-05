[CmdletBinding()]
param(
    [switch]$Setup,
    [switch]$ApiOnly,
    [switch]$Restart
)

$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Frontend = Join-Path $Root "processing_debug_frontend"
$ModelCache = Join-Path $Root ".model-cache"
$UploadTemp = Join-Path $Root ".tmp\uploads"

function Test-LocalUrl {
    param([Parameter(Mandatory)][string]$Url)

    try {
        Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

function Test-LocalPort {
    param([Parameter(Mandatory)][int]$Port)

    try {
        return $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1)
    }
    catch {
        return $false
    }
}

function Stop-LocalListener {
    param(
        [Parameter(Mandatory)][int]$Port,
        [Parameter(Mandatory)][string]$ServiceName
    )

    $Listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    foreach ($Listener in $Listeners) {
        $ProcessId = $Listener.OwningProcess
        if ($ProcessId) {
            Stop-Process -Id $ProcessId -Force -ErrorAction Stop
            Write-Host "Stopped $ServiceName process $ProcessId on port $Port."
        }
    }
}

function ConvertTo-EncodedPowerShell {
    param([Parameter(Mandatory)][string]$Script)

    return [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Script))
}

function Find-BootstrapPython {
    $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    $Candidates = @(
        [PSCustomObject]@{ Path = "A:\Anaconda\Download\envs\RVCE_CVHackathon\python.exe"; Arguments = @() }
        [PSCustomObject]@{ Path = if ($PyLauncher) { $PyLauncher.Source } else { $null }; Arguments = @("-3.11") }
        [PSCustomObject]@{ Path = if ($PyLauncher) { $PyLauncher.Source } else { $null }; Arguments = @("-3.12") }
        [PSCustomObject]@{ Path = if ($PythonCommand) { $PythonCommand.Source } else { $null }; Arguments = @() }
    )

    foreach ($Candidate in $Candidates) {
        if (-not $Candidate.Path) {
            continue
        }

        if ($Candidate.Path -ne "py.exe" -and -not (Test-Path -LiteralPath $Candidate.Path)) {
            continue
        }

        & $Candidate.Path @($Candidate.Arguments) -c "import sys; raise SystemExit(0 if sys.version_info[:2] in ((3, 11), (3, 12)) else 1)" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            return $Candidate
        }
    }

    return $null
}

if (-not $ApiOnly -and -not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop is required to run Qdrant. Install/start Docker Desktop, then run this command again."
}

Set-Location -LiteralPath $Root

if (-not (Test-Path -LiteralPath $Python)) {
    if (-not $Setup) {
        throw "The local Python environment is missing. Run .\start-local.ps1 -Setup once."
    }

    $BootstrapPython = Find-BootstrapPython
    if (-not $BootstrapPython) {
        throw "Python 3.11 or 3.12 is required. Install it, then run .\start-local.ps1 -Setup again."
    }

    & $BootstrapPython.Path @($BootstrapPython.Arguments) -m venv .venv
}

if ($Setup) {
    & $Python -m pip install -r requirements-processing.txt -r requirements.txt

    $Npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $Npm) {
        throw "Node.js and npm are required. Install Node.js, then run .\start-local.ps1 -Setup again."
    }
    Push-Location -LiteralPath $Frontend
    try {
        & $Npm.Source ci
    }
    finally {
        Pop-Location
    }
}

if ($ApiOnly) {
    Write-Host "API-only mode: skipping local Qdrant and Docker. Configure Qdrant Cloud in the Architecture page."
}
elseif (-not (Test-LocalUrl "http://127.0.0.1:6333/healthz")) {
    if (Test-LocalPort 6333) {
        Write-Warning "Qdrant is already listening on port 6333, but its health probe is slow. Skipping Docker startup."
    }
    else {
        & docker compose up -d qdrant
    }
}
else {
    Write-Host "Qdrant is already running."
}

if ($Restart -and (Test-LocalPort 8000)) {
    Stop-LocalListener -Port 8000 -ServiceName "processing API"
}

if ((Test-LocalPort 8000) -and -not (Test-LocalUrl "http://127.0.0.1:8000/api/runtime/profiles")) {
    throw "Port 8000 is occupied by an older or different API process. Run .\\start-local.ps1 -Restart to replace it with this project's processing API."
}

if (-not (Test-LocalUrl "http://127.0.0.1:8000/api/runtime/profiles")) {
    $EscapedRoot = $Root.Replace("'", "''")
    $EscapedPython = $Python.Replace("'", "''")
    $EscapedModelCache = $ModelCache.Replace("'", "''")
    $EscapedUploadTemp = $UploadTemp.Replace("'", "''")
    $BackendScript = @"
Set-Location -LiteralPath '$EscapedRoot'
New-Item -ItemType Directory -Force -Path '$EscapedUploadTemp' | Out-Null
`$env:HF_HOME = '$EscapedModelCache'
`$env:TEMP = '$EscapedUploadTemp'
`$env:TMP = '$EscapedUploadTemp'
`$env:OPENBLAS_NUM_THREADS = '1'
`$env:OMP_NUM_THREADS = '1'
`$env:PYTHONPATH = ''
`$env:QUERY_LOW_MEMORY_MODE = '1'
& '$EscapedPython' -m uvicorn processing_indexing.debug_api:app --host 127.0.0.1 --port 8000
"@
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", (ConvertTo-EncodedPowerShell $BackendScript)) -WindowStyle Hidden
    Write-Host "Started the processing API."
}
else {
    Write-Host "The processing API is already running."
}

if ($Restart -and (Test-LocalPort 3000)) {
    Stop-LocalListener -Port 3000 -ServiceName "browser UI"
}

if (-not (Test-LocalUrl "http://127.0.0.1:3000")) {
    $Npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $Npm) {
        throw "Node.js and npm are required. Install Node.js, then run .\start-local.ps1 again."
    }
    $EscapedFrontend = $Frontend.Replace("'", "''")
    $EscapedNpm = $Npm.Source.Replace("'", "''")
    $FrontendScript = @"
Set-Location -LiteralPath '$EscapedFrontend'
`$env:NEXT_PUBLIC_PROCESSING_API_URL = 'http://127.0.0.1:8000'
& '$EscapedNpm' run dev -- --hostname 127.0.0.1 --port 3000
"@
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", (ConvertTo-EncodedPowerShell $FrontendScript)) -WindowStyle Hidden
    Write-Host "Started the browser UI."
}
else {
    Write-Host "The browser UI is already running."
}

Write-Host ""
Write-Host "Open http://127.0.0.1:3000"
if ($ApiOnly) {
    Write-Host "If this is the first run, wait briefly for the API and browser UI to finish starting."
}
else {
    Write-Host "If this is the first run, wait briefly for the local services to finish starting."
}
