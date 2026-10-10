param([Parameter(Mandatory = $false)][string]$ScoopHome)
$ErrorActionPreference = 'Stop'

# Keep this matrix tied to the exact Scoop comparison implementation used by
# the bucket CI. Do not silently inherit a moving checkout or a local install.
$scoopVersionsCommit = 'e6aa3b366bdee8ed138c1e0f7b85192ebdd35d0f'
$scoopVersionsSha256 = '062261ae41f24699991fc6fd8f1b941ce78a81764bcae921e058b68637e5e454'
$versionsPath = Join-Path ([IO.Path]::GetTempPath()) "scoop-versions-$([guid]::NewGuid()).ps1"
try {
    Invoke-WebRequest `
        -Uri "https://raw.githubusercontent.com/ScoopInstaller/Scoop/$scoopVersionsCommit/lib/versions.ps1" `
        -OutFile $versionsPath -UseBasicParsing
    if ((Get-FileHash $versionsPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $scoopVersionsSha256) {
        throw 'Pinned Scoop lib/versions.ps1 digest mismatch'
    }
    . $versionsPath
    if (!(Get-Command Compare-Version -ErrorAction SilentlyContinue)) {
        throw 'Pinned Scoop lib/versions.ps1 does not define Compare-Version'
    }

    $ascending = @(
        @('0.0.0-alpha.dev.1-r1', '26.1009.7.410-alpha.dev.1-r1'),
        @('26.1009.7.410-alpha.dev.1-r1', '26.1009.7.410-alpha.dev.1-r2'),
        @('26.1009.7.410-alpha.dev.1-r9', '26.1009.7.410-alpha.dev.1-r10'),
        @('26.1009.7.410-alpha.dev.1-r10', '26.1010.1.100-alpha.dev.1-r1'),
        @('26.1010.1.100-alpha.dev.1-r1', '26.1010.1.100-r1'),
        @('26.1009.7.410-r1', '26.1010.1.100-r1')
    )
    foreach ($pair in $ascending) {
        if ((Compare-Version $pair[0] $pair[1]) -ne 1) { throw "Upgrade ordering failed: $($pair[0]) -> $($pair[1])" }
        if ((Compare-Version $pair[1] $pair[0]) -ne -1) { throw "Downgrade ordering failed: $($pair[1]) -> $($pair[0])" }
    }
    foreach ($version in @(
        '0.0.0-alpha.dev.1-r1',
        '26.1009.7.410-alpha.dev.1-r1',
        '26.1009.7.410-alpha.dev.1-r2',
        '26.1009.7.410-r1',
        '26.1010.1.100-r1'
    )) {
        if ((Compare-Version $version $version) -ne 0) { throw "Equality ordering failed: $version" }
    }
    Write-Host "Scoop Compare-Version ordering passed at $scoopVersionsCommit"
} finally {
    Remove-Item $versionsPath -Force -ErrorAction SilentlyContinue
}
