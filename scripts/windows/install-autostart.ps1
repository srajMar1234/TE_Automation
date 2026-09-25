#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Register a Windows Scheduled Task so PM2 / TE Report Studio starts after reboot.

.DESCRIPTION
  Creates task "TE-Report-Studio-PM2" that runs scripts\windows\pm2-start.cmd at system startup.
  Also runs an initial `pm2 start` + `pm2 save` if the app is not yet registered.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\windows\install-autostart.ps1
#>

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$StartCmd = Join-Path $ProjectRoot "scripts\windows\pm2-start.cmd"
$TaskName = "TE-Report-Studio-PM2"

if (-not (Test-Path $StartCmd)) {
  throw "Missing launcher: $StartCmd"
}

# Ensure runtime folders exist
@(
  "logs",
  "data\cutover_history",
  "downloads\exports",
  "output"
) | ForEach-Object {
  $p = Join-Path $ProjectRoot $_
  if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p | Out-Null }
}

# First-time PM2 register + dump process list
Push-Location $ProjectRoot
try {
  if (-not (Get-Command pm2 -ErrorAction SilentlyContinue)) {
    throw "pm2 not found on PATH. Install Node.js LTS, then: npm install -g pm2"
  }
  $described = & pm2 describe te-report-studio 2>$null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Starting TE Report Studio with PM2..."
    & pm2 start ecosystem.config.cjs
  }
  & pm2 save
  & pm2 status
}
finally {
  Pop-Location
}

# Prefer the interactive user who will keep a session for Chrome/Playwright if needed.
# ONSTART + highest privileges; runs whether or not someone is logged in.
$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$StartCmd`"" -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -RestartCount 3 `
  -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit (New-TimeSpan -Hours 0)

$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $Action `
  -Trigger $Trigger `
  -Settings $Settings `
  -Principal $Principal `
  -Description "Auto-start PM2 / TE Report Studio after Windows reboot" | Out-Null

Write-Host ""
Write-Host "Scheduled task '$TaskName' registered (At Startup)."
Write-Host "Verify:  Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "Manual:  schtasks /Run /TN `"$TaskName`""
Write-Host "Studio:  http://<VM-IP>:8501"
