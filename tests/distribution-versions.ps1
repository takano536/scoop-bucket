param([Parameter(Mandatory = $true)][string]$ScoopHome)
$ErrorActionPreference = 'Stop'
. "$ScoopHome/lib/versions.ps1"
$ascending = @(
    @('0.0.0-alpha.dev.1-r1', '0.0.0-alpha.dev.2-r1'),
    @('0.0.0-alpha.dev.9-r1', '0.0.0-alpha.dev.10-r1'),
    @('0.0.0-alpha.dev.1-r1', '0.0.0-alpha.dev.1-r2'),
    @('0.0.0-alpha.dev.1-r9', '0.0.0-alpha.dev.1-r10'),
    @('0.0.0-alpha.dev.10-r10', '0.0.0-r1'),
    @('0.0.0-alpha.dev.10-r10', '2026.9.24-r1'),
    @('0.0.0-alpha.dev.10-r10', '2026.10.1-r1'),
    @('0.0.0-r1', '2026.10.1-r1')
)
foreach ($pair in $ascending) {
    if ((Compare-Version $pair[0] $pair[1]) -ne 1) { throw "Upgrade ordering failed: $($pair[0]) -> $($pair[1])" }
    if ((Compare-Version $pair[1] $pair[0]) -ne -1) { throw "Downgrade ordering failed: $($pair[1]) -> $($pair[0])" }
}
foreach ($version in @(
    '0.0.0-alpha.dev.1-r1',
    '0.0.0-alpha.dev.9-r10',
    '0.0.0-r1',
    '2026.9.24-r1',
    '2026.10.1-r1'
)) {
    if ((Compare-Version $version $version) -ne 0) { throw "Equality ordering failed: $version" }
}
Write-Host 'Scoop development/stable version ordering passed'
