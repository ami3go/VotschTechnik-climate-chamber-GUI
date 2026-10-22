#requires -Version 5.1
<#
.SYNOPSIS
  Stop and unregister the pre-production Climate Chamber scheduled task.
#>
[CmdletBinding()]
param([string]$TaskName = "ClimateChamberPreProduction")
$ErrorActionPreference = "Stop"
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "Task '$TaskName' is not registered."
    return
}
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed task '$TaskName'. The server process (if any) stopped with it."
