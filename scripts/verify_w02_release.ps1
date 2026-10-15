#requires -Version 5.1
<# W02: offline target-side verification using an INDEPENDENTLY TRUSTED frozen verifier.
   The verifier EXE, its SHA-256 pin, this wrapper and the publisher key MUST
   be provisioned by a trusted site process separately from the W02 ZIP.
   A ZIP's own hash or embedded key cannot establish publisher authenticity.
   Does not launch the GUI, install packages, connect hardware, or use network.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Archive,
    [Parameter(Mandatory = $true)][string]$InstallDir,
    [Parameter(Mandatory = $true)][string]$VerifierPath,
    [Parameter(Mandatory = $true)][string]$VerifierSha256,
    [Parameter(Mandatory = $true)][string]$TrustedPublicKey,
    [Parameter(Mandatory = $true)][string]$MinimumVersion
)
$ErrorActionPreference = "Stop"
if ($VerifierSha256 -cnotmatch '^[a-f0-9]{64}$') { throw "Externally pinned verifier SHA-256 required" }
if ($MinimumVersion -notmatch '^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?$') {
    throw "Externally pinned minimum release version required"
}
$archiveFile = [IO.Path]::GetFullPath($Archive)
$destination = [IO.Path]::GetFullPath($InstallDir)
$verifier = [IO.Path]::GetFullPath($VerifierPath)
$key = [IO.Path]::GetFullPath($TrustedPublicKey)
foreach ($path in @($archiveFile, $verifier, $key)) {
    if (-not [IO.File]::Exists($path)) { throw "Missing required offline verification input" }
}
if ([IO.Directory]::Exists($destination) -or [IO.File]::Exists($destination)) {
    throw "Target installation directory already exists"
}
if ($archiveFile -eq $verifier -or $archiveFile -eq $key -or $verifier -eq $key) {
    throw "Release, verifier and trusted publisher key must be distinct files"
}
$actual = (Get-FileHash -LiteralPath $verifier -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -cne $VerifierSha256) { throw "Standalone verifier authenticity pin mismatch" }
& $verifier --archive $archiveFile --install-dir $destination --public-key $key --min-version $MinimumVersion
if ($LASTEXITCODE -ne 0) { throw "Signed W02 release verification FAILED; no launch permitted" }
Write-Host "Signed offline release verified and staged. Simulation-only; deployment authorization still required."
