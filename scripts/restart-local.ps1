param(
  [int]$BackendPort = 8021,
  [int]$FrontendPort = 5173,
  [string]$BackendDir = "C:\work\stocks\stocklean\backend",
  [string]$FrontendDir = "C:\work\stocks\stocklean\frontend",
  [switch]$Visible,
  [switch]$Reload
)

$ErrorActionPreference = "Stop"

$BackendPort = [int]([array]$BackendPort)[0]
$FrontendPort = [int]([array]$FrontendPort)[0]

$pidFile = Join-Path $PSScriptRoot ".restart-local.pids.json"
$lockFile = Join-Path $PSScriptRoot ".restart-local.lock"
$logDir = Join-Path (Split-Path $PSScriptRoot -Parent) "logs"

if (!(Test-Path $logDir)) {
  New-Item -ItemType Directory -Path $logDir | Out-Null
}

function Stop-PortListener {
  param([int]$Port)
  $procIds = @()
  try {
    $procIds = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
      Select-Object -ExpandProperty OwningProcess
  } catch {
    $procIds = @()
  }
  $procIds = $procIds | Sort-Object -Unique
  foreach ($procId in $procIds) {
    try { Stop-Process -Id $procId -Force -ErrorAction Stop } catch {}
  }
}

function Stop-PortListenerNetstat {
  param([int]$Port)
  $lines = netstat -ano | Where-Object { $_ -match ":$Port\\s+.*LISTENING" }
  $procIds = $lines | ForEach-Object { ($_ -split '\\s+')[-1] } | Sort-Object -Unique
  foreach ($procId in $procIds) {
    try { Stop-Process -Id $procId -Force -ErrorAction Stop } catch {}
  }
}

function Start-WindowProcess {
  param(
    [string]$FilePath,
    [string[]]$ArgumentList,
    [string]$WorkingDirectory,
    [string]$StdOut,
    [string]$StdErr
  )
  $args = @{
    FilePath               = $FilePath
    ArgumentList           = $ArgumentList
    WorkingDirectory       = $WorkingDirectory
    PassThru               = $true
    RedirectStandardOutput = $StdOut
    RedirectStandardError  = $StdErr
  }
  if (-not $Visible) {
    $args["WindowStyle"] = "Hidden"
  }
  $proc = Start-Process @args
  return $proc.Id
}

function Stop-TrackedProcesses {
  if (!(Test-Path $pidFile)) {
    return
  }
  try {
    $payload = Get-Content $pidFile -Raw | ConvertFrom-Json
  } catch {
    $payload = $null
  }
  if ($payload) {
    foreach ($entry in $payload) {
      if ($entry.pid) {
        Stop-ProcessTree -ProcId $entry.pid
      }
    }
  }
  Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

function Stop-ProcessTree {
  param([int]$ProcId)
  $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcId" -ErrorAction SilentlyContinue
  foreach ($child in $children) {
    Stop-ProcessTree -ProcId $child.ProcessId
  }
  try { Stop-Process -Id $ProcId -Force -ErrorAction Stop } catch {}
}

function Stop-ByCommandLine {
  param([string]$Pattern)
  $matches = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like $Pattern }
  foreach ($proc in $matches) {
    Stop-ProcessTree -ProcId $proc.ProcessId
  }
}

function Stop-ByCommandLineRegex {
  param([string]$Pattern)
  $matches = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match $Pattern }
  foreach ($proc in $matches) {
    Stop-ProcessTree -ProcId $proc.ProcessId
  }
}

function Test-PortInUse {
  param([int]$Port)
  $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if ($listeners) {
    return $true
  }
  $lines = netstat -ano | Where-Object { $_ -match ":$Port\\s+.*LISTENING" }
  return ($lines.Count -gt 0)
}

function Resolve-FreePort {
  param([int]$Port, [int[]]$Fallbacks)
  if (-not (Test-PortInUse -Port $Port)) {
    return $Port
  }
  foreach ($candidate in $Fallbacks) {
    if (-not (Test-PortInUse -Port $candidate)) {
      return $candidate
    }
  }
  return $Port
}

function Wait-ForPortRelease {
  param([int]$Port, [int]$TimeoutSeconds = 8)
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $listeners) {
      return
    }
    Start-Sleep -Milliseconds 250
  }
}

if (Test-Path $lockFile) {
  Write-Host "Detected existing lock file: $lockFile (previous run may have been interrupted)." -ForegroundColor Yellow
}
Set-Content -Path $lockFile -Value $PID

try {
  $ports = @($BackendPort, $FrontendPort)
  Write-Host "Stopping listeners on ports: $($ports -join ', ')" -ForegroundColor Cyan
  Stop-TrackedProcesses
  Stop-ByCommandLine -Pattern "*uvicorn app.main:app*"
  Stop-ByCommandLineRegex -Pattern "uvicorn\\s+app\\.main:app"
  Stop-ByCommandLineRegex -Pattern "stocklean\\\\backend.*--port\\s+$BackendPort"
  Stop-ByCommandLine -Pattern "*npm run dev*"
  Stop-ByCommandLineRegex -Pattern "stocklean\\\\frontend.*vite"
  Stop-ByCommandLineRegex -Pattern "vite\\.js"
  Stop-ByCommandLineRegex -Pattern "stocklean\\\\frontend.*--port\\s+$FrontendPort"
  foreach ($port in $ports) {
    Stop-PortListener -Port $port
    Stop-PortListenerNetstat -Port $port
    Wait-ForPortRelease -Port $port
  }

  $backendPortValue = [int]($BackendPort | Select-Object -First 1)
  $frontendPortValue = [int]($FrontendPort | Select-Object -First 1)
  $backendPortPlus = $backendPortValue + 1
  $frontendPortPlus = $frontendPortValue + 1
  $resolvedBackendPort = Resolve-FreePort -Port $backendPortValue -Fallbacks @($backendPortPlus, 8021, 8022, 8031, 8041, 9000)
  $resolvedFrontendPort = Resolve-FreePort -Port $frontendPortValue -Fallbacks @($frontendPortPlus, 5174, 5175, 5180)
  if ($resolvedBackendPort -ne $BackendPort) {
    Write-Host "Backend port $BackendPort is in use; switching to $resolvedBackendPort." -ForegroundColor Yellow
  }
  if ($resolvedFrontendPort -ne $FrontendPort) {
    Write-Host "Frontend port $FrontendPort is in use; switching to $resolvedFrontendPort." -ForegroundColor Yellow
  }

$backendPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
if (!(Test-Path $backendPython)) {
  Write-Error "Backend venv not found: $backendPython"
  exit 1
}
$npmCmd = $null
try {
  $npmSource = (Get-Command npm -ErrorAction Stop).Source
  $npmCmd = Join-Path (Split-Path $npmSource) "npm.cmd"
} catch {
  $npmCmd = "npm.cmd"
}
if (!(Test-Path $npmCmd)) {
  $npmCmd = "npm.cmd"
}

Write-Host "Starting backend (uvicorn)..." -ForegroundColor Cyan
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backendLog = Join-Path $logDir "backend-$timestamp.log"
$backendErrLog = Join-Path $logDir "backend-$timestamp.err.log"
$frontendLog = Join-Path $logDir "frontend-$timestamp.log"
$frontendErrLog = Join-Path $logDir "frontend-$timestamp.err.log"
$backendArgs = @(
  "-m",
  "uvicorn",
  "app.main:app"
)
if ($Reload) {
  $backendArgs += "--reload"
}
$backendArgs += @(
  "--app-dir",
  $BackendDir,
  "--host",
  "0.0.0.0",
  "--port",
  "$resolvedBackendPort"
)
$backendPid = Start-WindowProcess -FilePath $backendPython -ArgumentList $backendArgs `
  -WorkingDirectory $BackendDir -StdOut $backendLog -StdErr $backendErrLog

Write-Host "Starting frontend (vite)..." -ForegroundColor Cyan
$apiBase = "http://localhost:$resolvedBackendPort"
$frontendCommand = "set VITE_API_BASE_URL=$apiBase && `"$npmCmd`" run dev -- --host 0.0.0.0 --port $resolvedFrontendPort"
$frontendArgs = @("/c", $frontendCommand)
$frontendPid = Start-WindowProcess -FilePath "cmd.exe" -ArgumentList $frontendArgs `
  -WorkingDirectory $FrontendDir -StdOut $frontendLog -StdErr $frontendErrLog

@(
  @{ name = "backend"; pid = $backendPid; port = $resolvedBackendPort },
  @{ name = "frontend"; pid = $frontendPid; port = $resolvedFrontendPort }
) | ConvertTo-Json | Set-Content -Path $pidFile

Write-Host "Logs: $backendLog, $backendErrLog, $frontendLog, $frontendErrLog" -ForegroundColor Cyan
} finally {
  Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
}
