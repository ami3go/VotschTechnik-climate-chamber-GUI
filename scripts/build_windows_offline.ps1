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
.PARAMETER UseReviewedClosure
  Install the runtime from the REVIEWED, hash-locked dependency closure
  (requirements-w02-runtime.lock) out of a verified wheelhouse, with no index
  access at all. The frozen bundle then contains exactly the reviewed
  artifacts, and its SBOM and license inventory describe that closure instead
  of the build environment. Without this switch the historical connected
  resolution is used and the build environment inventory is reported.
#>
[CmdletBinding()]
param(
    [switch]$Clean,
    [string]$OutputDir = "dist",
    [ValidateSet("Portable")][string]$Configuration = "Portable",
    [ValidatePattern('^[0-9A-Za-z][0-9A-Za-z.+-]{0,48}$')][string]$Version = "0.1.0-w01",
    [string]$Python = "python",
    [switch]$SimulationOnly,
    [switch]$UseReviewedClosure,
    [string]$WheelhouseDir = ""
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
    $closureLock = Join-Path $repo "requirements-w02-runtime.lock"
    $closureManifest = Join-Path $repo "w02-closure-manifest.json"
    $wheelhouse = if ($WheelhouseDir) { $WheelhouseDir } else { Join-Path $work "wheelhouse" }
    if ($UseReviewedClosure) {
        # The reviewed closure: hash-locked, complete, and installed with NO
        # index access. The frozen bundle then contains exactly the artifacts
        # that were reviewed, and the build fails closed if the closure can no
        # longer be reproduced from the pinned requirements.
        if (-not (Test-Path $closureLock)) { throw "The reviewed closure lock is missing" }
        if (-not (Test-Path $closureManifest)) { throw "The reviewed closure manifest is missing" }
        New-Item -Path $wheelhouse -ItemType Directory -Force | Out-Null
        # A separate tool environment keeps the build requirements (the pinned
        # build backend, the marker parser) out of the runtime environment that
        # is frozen into the bundle.
        Native $Python @("-m", "venv", (Join-Path $work "closure-venv"))
        $closurePy = Join-Path $work "closure-venv/Scripts/python.exe"
        Native $closurePy @("-m", "pip", "install", "--disable-pip-version-check",
                            "-r", (Join-Path $repo "requirements-w02-build.txt"))
        Push-Location $repo
        try {
            Native $closurePy @("-m", "scripts.w02_closure", "build",
                                "--requirements", (Join-Path $repo "requirements-web.txt"),
                                "--vcs-requirement", (Join-Path $repo "requirements-hardware.txt"),
                                "--wheelhouse", $wheelhouse,
                                "--lock", (Join-Path $work "closure.lock"),
                                "--manifest", (Join-Path $work "closure-manifest.json"),
                                "--target", "win_amd64-cp312", "--version", $Version)
            # Fail closed unless the rebuilt closure IS the reviewed one.
            Native $closurePy @("-m", "scripts.w02_closure", "verify",
                                "--wheelhouse", $wheelhouse, "--lock", $closureLock,
                                "--manifest", $closureManifest, "--target", "win_amd64-cp312")
        }
        finally { Pop-Location }
        Native $py @("-m", "pip", "install", "--disable-pip-version-check",
                     "--no-index", "--find-links", $wheelhouse, "--require-hashes",
                     "-r", $closureLock)
    }
    else {
        Native $py @("-m", "pip", "install", "--disable-pip-version-check", "-r",
                     (Join-Path $repo "requirements-web.txt"))
        if (-not $SimulationOnly) {
            # Fails closed if native Git or the exact pinned driver revision is unavailable.
            Native $py @("-m", "pip", "install", "--disable-pip-version-check", "-r",
                         (Join-Path $repo "requirements-hardware.txt"))
        }
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
    if ($UseReviewedClosure) {
        # The SBOM and the license inventory describe the reviewed runtime
        # closure, not the build environment, and the closure digest is
        # recorded with the manifest.
        $manifestArgs += @("--closure-manifest", $closureManifest,
                            "--closure-lock", $closureLock)
    }
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
