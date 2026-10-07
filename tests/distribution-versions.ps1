param([Parameter(Mandatory = $true)][string]$ScoopHome)
$ErrorActionPreference = 'Stop'
. "$ScoopHome/lib/versions.ps1"
foreach ($pair in @(
    @('0.22.0-r1', '0.22.0-r2'),
    @('0.22.0-r2', '0.22.0-r10'),
    @('0.22.0-r10', '0.23.0-r1')
)) {
    if ((Compare-Version $pair[0] $pair[1]) -ne 1) { throw "Upgrade ordering failed: $pair" }
    if ((Compare-Version $pair[1] $pair[0]) -ne -1) { throw "Downgrade ordering failed: $pair" }
}
if ((Compare-Version '0.22.0-r1' '0.22.0-r1') -ne 0) { throw 'Idempotent version comparison failed' }
Write-Host 'Scoop distribution revision ordering passed'
