#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Remove the TE Report Studio PM2 startup scheduled task.
#>
$TaskName = "TE-Report-Studio-PM2"
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Removed scheduled task '$TaskName' (if it existed)."
Write-Host "Optional: pm2 delete te-report-studio ; pm2 save --force"
