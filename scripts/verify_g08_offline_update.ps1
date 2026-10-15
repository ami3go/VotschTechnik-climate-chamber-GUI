# G08 fail-closed offline update gate for a future signed W02 ZIP.
# This does not install or execute a package and never touches physical I/O.
# The expected ZIP SHA-256 and approved signer thumbprint MUST be obtained
# through an independent trusted channel, NOT from inside the ZIP.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Package,
    [Parameter(Mandatory = $true)][string]$ExpectedSha256,
    [Parameter(Mandatory = $true)][string]$PublisherThumbprint
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($ExpectedSha256 -notmatch '^[a-fA-F0-9]{64}$') {
    throw 'An independently approved 64-digit ZIP SHA-256 is required'
}
if ($PublisherThumbprint -notmatch '^[a-fA-F0-9]{40,64}$') {
    throw 'An independently approved publisher certificate thumbprint is required'
}
$zip = (Resolve-Path -LiteralPath $Package -ErrorAction Stop).ProviderPath
if (-not [System.IO.File]::Exists($zip)) { throw 'Missing offline update ZIP' }
$actual = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
if ($actual -ine $ExpectedSha256) { throw 'Offline package SHA-256 mismatch' }

$extract = Join-Path ([System.IO.Path]::GetTempPath()) (
    'Chamber-G08-Verify-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($extract) | Out-Null
try {
    Expand-Archive -LiteralPath $zip -DestinationPath $extract -ErrorAction Stop
    $manifests = @(Get-ChildItem -LiteralPath $extract -Recurse -File |
        Where-Object { $_.Name -eq 'build-manifest.json' })
    if ($manifests.Count -ne 1) { throw 'Exactly one build manifest required' }
    $bundle = $manifests[0].Directory.FullName
    $manifest = Get-Content -LiteralPath $manifests[0].FullName -Raw |
        ConvertFrom-Json
    if ($manifest.architecture -ne 'Windows-x64') {
        throw 'Incorrect architecture in update manifest'
    }
    if ($manifest.distribution -notmatch 'SIMULATION ONLY') {
        # Full signed releases must use a separately reviewed W02 schema.
        throw 'W02 publisher/release schema not yet approved'
    }
    $tracked = @{}
    foreach ($entry in @($manifest.files.PSObject.Properties)) {
        $name = [string]$entry.Name
        if (($name -match '[\\:]') -or $name.StartsWith('/') -or
            ($name -split '/') -contains '..') {
            throw ('Unsafe manifest path: ' + $name)
        }
        $path = Join-Path $bundle ($name.Replace('/', [IO.Path]::DirectorySeparatorChar))
        if (-not [IO.File]::Exists($path)) { throw ('Missing bundle file: ' + $name) }
        $full = [IO.Path]::GetFullPath($path)
        $root = [IO.Path]::GetFullPath($bundle + [IO.Path]::DirectorySeparatorChar)
        if (-not $full.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Manifest path escapes bundle root'
        }
        $hash = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash
        if ($hash -ine [string]$entry.Value) {
            throw ('Offline manifest content hash mismatch: ' + $name)
        }
        $tracked[$name] = $true
    }
    $all = @(Get-ChildItem -LiteralPath $bundle -Recurse -File |
        ForEach-Object { $_.FullName.Substring($bundle.Length + 1).Replace('\\', '/') } |
        Where-Object { $_ -ne 'build-manifest.json' -and $_ -ne 'SHA256SUMS.txt' })
    foreach ($name in $all) {
        if (-not $tracked.ContainsKey($name)) { throw ('Unsigned file in bundle: ' + $name) }
    }
    if ($all.Count -ne $tracked.Count) { throw 'Invalid tracked bundle file count' }
    foreach ($exe in @('ClimateChamberLauncher.exe',
                       'server/ClimateChamberServer.exe')) {
        if (-not $tracked.ContainsKey($exe)) { throw ('Missing executable: ' + $exe) }
        $filename = Join-Path $bundle ($exe.Replace('/', [IO.Path]::DirectorySeparatorChar))
        $signature = Get-AuthenticodeSignature -LiteralPath $filename
        if ($signature.Status -ne 'Valid' -or
            $null -eq $signature.SignerCertificate -or
            $signature.SignerCertificate.Thumbprint -ine $PublisherThumbprint) {
            throw ('Invalid or unauthorized Authenticode signature: ' + $exe)
        }
    }
    Write-Output 'Offline update integrity and publisher validation passed (SIMULATOR ONLY)'
}
finally {
    Remove-Item -LiteralPath $extract -Recurse -Force -ErrorAction SilentlyContinue
}
