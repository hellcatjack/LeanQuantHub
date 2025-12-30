param(
  [int[]]$Ports = @(8000, 8001),
  [switch]$ShowOnly,
  [switch]$RestartHttpService
)

$ErrorActionPreference = "Stop"

function Get-PidsFromNetTcp {
  param([int[]]$Ports)
  try {
    return Get-NetTCPConnection -LocalPort $Ports -State Listen -ErrorAction Stop |
      Select-Object -ExpandProperty OwningProcess
  } catch {
    return @()
  }
}

function Get-PidsFromNetstat {
  param([int[]]$Ports)
  $pattern = ($Ports | ForEach-Object { ":$_\\s+.*LISTENING\\s+\\d+$" }) -join "|"
  $lines = netstat -ano | Where-Object { $_ -match $pattern }
  return $lines | ForEach-Object { ($_ -replace "^\\s+", "") -split "\\s+" | Select-Object -Last 1 }
}

function Show-Listeners {
  param([int[]]$Ports)
  Write-Host "Listeners (Get-NetTCPConnection):" -ForegroundColor Cyan
  Get-NetTCPConnection -LocalPort $Ports -State Listen -ErrorAction SilentlyContinue |
    Sort-Object LocalPort, OwningProcess |
    Format-Table -AutoSize
  Write-Host ""
  Write-Host "Listeners (netstat -ano):" -ForegroundColor Cyan
  netstat -ano | Where-Object { $_ -match (":(" + ($Ports -join "|") + ")\\s+.*LISTENING") }
}

Write-Host "Target ports: $($Ports -join ', ')" -ForegroundColor Cyan
Show-Listeners -Ports $Ports

$pids = @()
$pids += Get-PidsFromNetTcp -Ports $Ports
$pids += Get-PidsFromNetstat -Ports $Ports
$pids = $pids | Where-Object { $_ -match "^[0-9]+$" } | Sort-Object -Unique

if (-not $pids) {
  Write-Host "No owning processes found via netstat/Get-NetTCPConnection." -ForegroundColor Yellow
} else {
  Write-Host "Candidate PIDs: $($pids -join ', ')" -ForegroundColor Yellow
  $pids | ForEach-Object {
    Get-Process -Id $_ -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,Path
  }
}

if ($ShowOnly) {
  Write-Host "ShowOnly enabled. No processes were stopped." -ForegroundColor Yellow
  exit 0
}

foreach ($pid in $pids) {
  try { Stop-Process -Id $pid -Force -ErrorAction Stop } catch {}
}

if ($RestartHttpService) {
  Write-Host "Restarting HTTP service (may disrupt local services)..." -ForegroundColor Yellow
  try {
    net stop http | Out-Null
    net start http | Out-Null
  } catch {}
}

Write-Host ""
Write-Host "After cleanup:" -ForegroundColor Cyan
Show-Listeners -Ports $Ports

Write-Host ""
Write-Host "If ports are still LISTENING as [System], run this script in an Administrator PowerShell or reboot." -ForegroundColor Yellow
