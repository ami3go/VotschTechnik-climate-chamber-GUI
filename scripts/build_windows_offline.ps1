#requires -Version 5.1
<#
.SYNOPSIS
  W01-A: Build simulated Windows x64 NiceGUI server + launcher offline ZIP.
.DESCRIPTION
  Native internet-connected Windows build host required. The target bundle
  does not call pip/uv/Git/CDN; full W02 air-gapped certification is pending.
.PARAMETER SimulationOnly
  Exclude the external vendor driver for a smaller, NON-RELEASE test artifact.
  Default includes pinned Vötsch dependency but DOES NOT enable hardware I/O.
#>
[CmdletBinding()]
param(
    [switch]$Clean,
    [string]$OutputDir = "dist",
    [ValidateSet("Portable")][string]$Configuration = "Portable",
    [ValidatePattern('^[0-9A-Za-z][0-9A-Za-z.+-]{0,48}$')][string]$Version = "0.1.0-w01",
    [string]$Python = "python",
    [switch]$SimulationOnly
)
$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") { throw "Build offline bundle natively on Windows." }
if (-not [Environment]::Is64BitOperatingSystem) { throw "Windows x64 is required." }
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([IO.Path]::IsPathRooted($OutputDir)) { $output = [IO.Path]::GetFullPath($OutputDir) }
else { $output = [IO.Path]::GetFullPath((Join-Path (Get-Location).Path $OutputDir)) }
New-Item -Path $output -ItemType Directory -Force | Out-Null
$name = "ClimateChamber-Web-Windows-x64-$Version-offline"
$zip = Join-Path $output ($name + ".zip")
$checksum = $zip + ".sha256"
if ($Clean) { Remove-Item $zip, $checksum -Force -ErrorAction SilentlyContinue }
if (Test-Path $zip) { throw "Output ZIP exists: $zip (use -Clean or a different version)" }
$work = Join-Path $env:TEMP ("chamber-offline-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $work | Out-Null
function Native([string]$command, [string[]]$arguments) {
    & $command @arguments
    if ($LASTEXITCODE -ne 0) { throw "Native command failed ($LASTEXITCODE): $command $($arguments -join ' ')" }
}
try {
    $bundle = Join-Path $work $name
    $server = Join-Path $bundle "server"
    New-Item -Path $server -ItemType Directory -Force | Out-Null
    Native $Python @("-m", "venv", (Join-Path $work "venv"))
    $py = Join-Path $work "venv/Scripts/python.exe"
    Native $py @("-m", "pip", "install", "--disable-pip-version-check", "-r",
                 (Join-Path $repo "requirements-web.txt"))
    if (-not $SimulationOnly) {
        # Fails closed if native Git or the exact pinned driver revision is unavailable.
        Native $py @("-m", "pip", "install", "--disable-pip-version-check", "-r",
                     (Join-Path $repo "requirements-hardware.txt"))
    }
    Native $py @("-m", "pip", "install", "--disable-pip-version-check", "pyinstaller==6.16.0")
    $freeze = @(
        "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--name", "ClimateChamberServer", "--paths", $repo,
        "--distpath", (Join-Path $work "frozen"), "--workpath", (Join-Path $work "build"),
        "--specpath", $work, "--collect-all", "nicegui", "--collect-data", "chamber_web",
        "--hidden-import", "chamber_web.adapters.fake",
        "--hidden-import", "chamber_web.adapters.alternate_stub",
        "--hidden-import", "chamber_web.adapters.votsch",
        "--hidden-import", "chamber_web.adapters.registry"
    )
    if (-not $SimulationOnly) { $freeze += @("--collect-all", "VotschTechnikClimateChamber") }
    $freeze += (Join-Path $repo "scripts/windows_server.py")
    Native $py $freeze
    Copy-Item (Join-Path $work "frozen/ClimateChamberServer/*") $server -Recurse -Force
    $serverExe = Join-Path $server "ClimateChamberServer.exe"
    if (-not (Test-Path $serverExe)) { throw "Frozen server executable is missing" }
    $testFlags = @("--self-test")
    if (-not $SimulationOnly) { $testFlags += @("--require-module", "VotschTechnikClimateChamber") }
    Native $serverExe $testFlags

    # Script A is a genuinely separate maintained thin-launcher build.
    & (Join-Path $repo "scripts/build_windows_launcher.ps1") -Clean -OutputDir $bundle -Configuration $Configuration -Version $Version -Python $Python
    if (-not $?) { throw "Launcher build failed" }
    Copy-Item (Join-Path $repo "README_OFFLINE_WINDOWS.md") $bundle
    Copy-Item (Join-Path $repo "scripts/create_windows_shortcuts.ps1") $bundle
    $manifestArgs = @((Join-Path $repo "scripts/windows_manifest.py"),
        "--bundle", $bundle, "--create", "--version", $Version,
        "--requirements-web", (Join-Path $repo "requirements-web.txt"),
        "--requirements-hardware", (Join-Path $repo "requirements-hardware.txt"))
    if (-not $SimulationOnly) { $manifestArgs += "--include-driver" }
    Native $py $manifestArgs
    # Fresh extraction and integrity verification before accepting the archive.
    Compress-Archive -Path $bundle -DestinationPath $zip -CompressionLevel Optimal
    $scratch = Join-Path $work "verify"
    Expand-Archive -LiteralPath $zip -DestinationPath $scratch
    Native $py @((Join-Path $repo "scripts/windows_manifest.py"), "--bundle",
                 (Join-Path $scratch $name), "--verify")
    ((Get-FileHash -Algorithm SHA256 $zip).Hash.ToLowerInvariant() +
      "  " + [IO.Path]::GetFileName($zip)) | Set-Content -Encoding ASCII $checksum
    Write-Host "Simulation-only runtime: physical chamber I/O DISABLED"
    Write-Host "Offline feasibility bundle: $zip"
    Write-Host "SHA256: $checksum"
}
finally { Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue }
