$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$root = (Get-Location).Path
$source = Join-Path $root 'upstream'
$out = Join-Path $root 'output'
New-Item -ItemType Directory -Path $out | Out-Null
$commit = (git -C $source rev-parse HEAD).Trim()
if ($env:PREVIEW -eq 'true') {
    python "$source/scripts/bundles/desktop.py" --commit $commit --variant light -- --dir
} else {
    if ($env:SOURCE_REF -cne "v$($env:PACKAGE_VERSION)") { throw 'Release identity mismatch' }
    python "$source/scripts/bundles/desktop.py" --tag $env:SOURCE_REF --variant light -- --dir
}
$pack = Join-Path $source 'apps/desktop/release/win-unpacked'
if (!(Test-Path $pack)) { throw 'No unpacked Windows application was built' }
$stamp = Get-Content "$pack/resources/install-stamp.json" -Raw | ConvertFrom-Json
if ($stamp.payload -cne 'light' -or $stamp.commit -cne $commit -or $stamp.updateMechanism -cne 'external') {
    throw 'Wrong payload, provenance, or update owner'
}
if (Test-Path "$pack/resources/agent-payload") { throw 'Light unexpectedly contains a local agent' }
$exes = @(Get-ChildItem $pack -Filter 'Hermes Light*.exe')
if ($exes.Count -ne 1) { throw 'Ambiguous product executable' }
if ($env:PREVIEW -ne 'true' -and $exes[0].Name -cne 'Hermes Light.exe') { throw 'Unstable product identity' }
# Use the exact managed Node admitted by upstream preparation.
$prepared = Get-Content "$source/.build/desktop-job/prepared.json" -Raw | ConvertFrom-Json
& $prepared.node "$root/bucket/scripts/smoke-hermes-light.cjs" $source $exes[0].FullName $out
$version = $env:PACKAGE_VERSION
if ($env:PREVIEW -eq 'true') { $version = "preview-$($commit.Substring(0, 7))" }
$name = "hermes-agent-light-$version-windows-x64.zip"
Compress-Archive -Path "$pack/*" -DestinationPath "$out/$name" -CompressionLevel Optimal
$receipt = @{
    schema = 1
    upstream = 'NousResearch/hermes-agent'
    sourceRef = $env:SOURCE_REF
    commit = $commit
    version = $version
    preview = ($env:PREVIEW -eq 'true')
    artifact = $name
    sha256 = (Get-FileHash "$out/$name" -Algorithm SHA256).Hash.ToLowerInvariant()
    payload = $stamp.payload
    updateMechanism = $stamp.updateMechanism
    executable = $exes[0].Name
    smoke = 'two native launches; renderer loaded; localStorage retained'
    signing = 'unsigned unofficial build'
    run = "https://github.com/$env:GITHUB_REPOSITORY/actions/runs/$env:GITHUB_RUN_ID"
}
$receipt | ConvertTo-Json -Depth 10 | Set-Content "$out/provenance.json" -Encoding utf8NoBOM
