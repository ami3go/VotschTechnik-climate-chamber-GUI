#requires -Version 5.1
<#
.SYNOPSIS
  Create a per-user Windows shortcut for the W01 simulation-only launcher.
.DESCRIPTION
  Does not install a service or create any privileged system-wide files.
  Default target: current user's Start Menu; -Desktop adds a per-user desktop link.
  -OutputDir is intended for CI verification and offline package staging.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Launcher,
    [string]$OutputDir = [Environment]::GetFolderPath("StartMenu") + "\\Programs\\Climate Chamber",
    [switch]$Desktop
)
$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") { throw "Windows shortcut creation requires Windows" }
$target = [IO.Path]::GetFullPath($Launcher)
if (-not (Test-Path -LiteralPath $target -PathType Leaf) -or
    [IO.Path]::GetExtension($target) -ne ".exe") { throw "Launcher executable not found: $target" }
$folder = [IO.Path]::GetFullPath($OutputDir)
New-Item -Path $folder -ItemType Directory -Force | Out-Null
$shell = New-Object -ComObject WScript.Shell
function Write-Shortcut([string]$directory) {
    New-Item -Path $directory -ItemType Directory -Force | Out-Null
    $file = Join-Path $directory "Climate Chamber (Simulation).lnk"
    $link = $shell.CreateShortcut($file)
    $link.TargetPath = $target
    $link.WorkingDirectory = [IO.Path]::GetDirectoryName($target)
    $link.Description = "W01-A local simulated climate chamber web dashboard (no real hardware)"
    $link.Save()
    if (-not (Test-Path -LiteralPath $file)) { throw "Shortcut creation failed: $file" }
    Write-Output $file
}
Write-Shortcut $folder
if ($Desktop) { Write-Shortcut ([Environment]::GetFolderPath("Desktop")) }
