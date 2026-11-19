#requires -Version 5.1
<#
.SYNOPSIS
  Register the pre-production Climate Chamber server as an at-logon task.

.DESCRIPTION
  The full server runs in the logged-in operator account so its state, logs,
  security database and supervised H02 journals stay in that user's
  %LOCALAPPDATA%. The task restarts on failure, never runs two instances, has
  no execution-time limit and starts when the machine was unavailable. This is
  a scheduled task, not a Windows service: browser sessions and the watchdog
  still belong to the interactive desktop session.

  Run the first-time administrator bootstrap interactively BEFORE registering:
      server\ClimateChamberServer.exe --bootstrap-admin

.PARAMETER ServerExe
  Path to ClimateChamberServer.exe (default: <bundle>\server\...).
.PARAMETER Config
  Path to chamber.env (default: <bundle>\chamber.env when present).
.PARAMETER Port
  UI port (default 8090).
.PARAMETER User
  Account name to run as (default: the current user).
.PARAMETER StartNow
  Also start the task immediately after registration.
#>
[CmdletBinding()]
param(
    [string]$ServerExe = "",
    [string]$Config = "",
    [int]$Port = 8090,
    [string]$User = "",
    [switch]$StartNow
)
$ErrorActionPreference = "Stop"
$taskName = "ClimateChamberPreProduction"
$bundle = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $ServerExe) { $ServerExe = Join-Path $bundle "server\ClimateChamberServer.exe" }
if (-not $Config) {
    $candidate = Join-Path $bundle "chamber.env"
    if (Test-Path $candidate) { $Config = $candidate }
}
if (-not (Test-Path $ServerExe)) { throw "Server executable not found: $ServerExe" }
if ($Config -and -not (Test-Path $Config)) { throw "Configuration file not found: $Config" }
if (-not $User) { $User = [Security.Principal.WindowsIdentity]::GetCurrent().Name }

$arguments = @("--port", "$Port")
if ($Config) { $arguments += @("--config", ('"' + $Config + '"')) }
$action = New-ScheduledTaskAction -Execute $ServerExe -Argument ($arguments -join " ") `
    -WorkingDirectory (Split-Path $ServerExe -Parent)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null
Write-Host "Registered task '$taskName' for $User (port $Port)."
if ($Config) { Write-Host "Configuration: $Config" }
Write-Host "Logs: $env:LOCALAPPDATA\ClimateChamber\App\app.log"
if ($StartNow) { Start-ScheduledTask -TaskName $taskName; Write-Host "Task started." }
