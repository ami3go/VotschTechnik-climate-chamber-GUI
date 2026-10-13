#requires -Version 5.1
<# W02 on-target verification (no Python). This script MUST be run with a
   pinned public key placed outside the archive by the site's trusted process. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Bundle,
    [Parameter(Mandatory = $true)][string]$TrustedPublicKey
)
$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath($Bundle)
$keyPath = [IO.Path]::GetFullPath($TrustedPublicKey)
if (-not (Test-Path -LiteralPath $keyPath -PathType Leaf)) { throw "Trusted key missing" }
$scriptPath = Join-Path $root 'w02-release.json'
$sigPath = Join-Path $root 'w02-release.sig'
if (-not (Test-Path -LiteralPath $scriptPath) -or -not (Test-Path -LiteralPath $sigPath)) { throw "Release signature missing" }
# Windows PowerShell 5.1 lacks native Ed25519. The separate W02 Python signing
# verifier is required on a trusted offline validation station; this script
# deliberately fails rather than treating hashes as a signature.
throw "NO-GO: Windows PowerShell 5.1 has no built-in Ed25519 verifier; use independent trusted offline verification station, not this script."
