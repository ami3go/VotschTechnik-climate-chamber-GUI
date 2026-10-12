#requires -Version 5.1
<#
.SYNOPSIS
  W01-A: Build a Windows browser launcher (NOT the complete offline app).
.PARAMETER Clean
  Remove only this launcher's generated output files before rebuilding.
.PARAMETER OutputDir
  Directory for ClimateChamberLauncher.exe and launcher-build.json.
.PARAMETER Configuration
  Portable mode is the only supported mode in W01-A.
.PARAMETER Version
  Display/build version recorded in the manifest (not Authenticode signing).
.PARAMETER Python
  Native Windows Python executable used to construct a clean build venv.
#>
[CmdletBinding()]
param(
    [switch]$Clean,
    [string]$OutputDir = "dist/windows-launcher",
    [ValidateSet("Portable")][string]$Configuration = "Portable",
    [ValidatePattern('^[0-9A-Za-z][0-9A-Za-z.+-]{0,48}$')][string]$Version = "0.1.0-w01",
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") { throw "Build launcher natively on Windows." }
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([IO.Path]::IsPathRooted($OutputDir)) { $output = [IO.Path]::GetFullPath($OutputDir) }
else { $output = [IO.Path]::GetFullPath((Join-Path (Get-Location).Path $OutputDir)) }
if (-not (Test-Path $output)) { New-Item -ItemType Directory -Path $output -Force | Out-Null }
if ($Clean) {
    @("ClimateChamberLauncher.exe", "launcher-build.json") | ForEach-Object {
        Remove-Item (Join-Path $output $_) -ErrorAction SilentlyContinue -Force
    }
}
$work = Join-Path $env:TEMP ("chamber-launcher-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $work | Out-Null
function Native([string]$command, [string[]]$arguments) {
    & $command @arguments
    if ($LASTEXITCODE -ne 0) { throw "Native command failed ($LASTEXITCODE): $command $($arguments -join ' ')" }
}
try {
    Native $Python @("-m", "venv", (Join-Path $work "venv"))
    $py = Join-Path $work "venv/Scripts/python.exe"
    Native $py @("-m", "pip", "install", "--disable-pip-version-check", "pyinstaller==6.16.0")
    Native $py @(
        "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "ClimateChamberLauncher", "--paths", $repo,
        "--distpath", $output, "--workpath", (Join-Path $work "build"),
        "--specpath", $work, (Join-Path $repo "scripts/windows_launcher.py")
    )
    $exe = Join-Path $output "ClimateChamberLauncher.exe"
    if (-not (Test-Path $exe)) { throw "Launcher executable missing: $exe" }
    $details = [ordered]@{
        schema = 1
        version = $Version
        configuration = $Configuration
        kind = "W01-A standalone browser launcher (server required)"
        sha256 = (Get-FileHash -Algorithm SHA256 $exe).Hash.ToLowerInvariant()
    }
    $details | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $output "launcher-build.json")
    Write-Host "Launcher built: $exe"
}
finally { Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue }
