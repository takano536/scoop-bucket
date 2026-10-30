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

    # Ascending pairs verified against the pinned Scoop implementation. They cover
    # the legacy CalendarVer -> official-tag migration and same-channel
    # official-tag ordering (revision bumps, later builds, rc numbers). Canary and
    # stable tags are separate packages and are never compared with each other.
    $ascending = @(
        @('0.0.0-alpha.dev.1-r1', 'v0.22.5+canary.20261023T070057Z-r1'),
        @('26.1023.7.57-alpha.dev.1-r1', 'v0.22.5+canary.20261023T070057Z-r1'),
        @('2026.6864.2132.0-r1', 'rc.3-v0.22.0-r1'),
        @('rc.3-v0.22.0-r1', 'rc.3-v0.22.0-r2'),
        @('rc.3-v0.22.0-r9', 'rc.3-v0.22.0-r10'),
        @('rc.3-v0.22.0-r2', 'rc.4-v0.22.1-r1'),
        @('v0.22.5+canary.20261023T070057Z-r1', 'v0.22.5+canary.20261024T065630Z-r1'),
        @('v0.22.5+canary.20261023T070057Z-r9', 'v0.22.5+canary.20261023T070057Z-r10'),
        @('v0.22.4+canary.20261022T070155Z-r1', 'v0.22.5+canary.20261023T070057Z-r1')
    )
    foreach ($pair in $ascending) {
        if ((Compare-Version $pair[0] $pair[1]) -ne 1) { throw "Upgrade ordering failed: $($pair[0]) -> $($pair[1])" }
        if ((Compare-Version $pair[1] $pair[0]) -ne -1) { throw "Downgrade ordering failed: $($pair[1]) -> $($pair[0])" }
    }
    foreach ($version in @(
        '0.0.0-alpha.dev.1-r1',
        '26.1023.7.57-alpha.dev.1-r1',
        '2026.6864.2132.0-r1',
        'rc.3-v0.22.0-r1',
        'rc.3-v0.22.0-r2',
        'rc.4-v0.22.1-r1',
        'v0.22.5+canary.20261023T070057Z-r1',
        'v0.22.5+canary.20261023T070057Z-r10',
        'v0.22.5+canary.20261024T065630Z-r1'
    )) {
        if ((Compare-Version $version $version) -ne 0) { throw "Equality ordering failed: $version" }
    }
    Write-Host "Scoop Compare-Version ordering passed at $scoopVersionsCommit"
} finally {
    Remove-Item $versionsPath -Force -ErrorAction SilentlyContinue
}
