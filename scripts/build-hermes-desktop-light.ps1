$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$root = (Get-Location).Path
$source = Join-Path $root 'upstream'
$out = Join-Path $root 'output'
New-Item -ItemType Directory -Path $out | Out-Null
$commit = (git -C $source rev-parse HEAD).Trim()
$development = $env:CHANNEL -eq 'development'
if ($commit -notmatch '^[a-f0-9]{40}$' -or $env:SOURCE_REF -cne $commit) {
    throw 'Builder checkout is not the exact admitted upstream commit'
}
if ($development -and
    ($env:LICENSE_SHA256 -cnotmatch '^[a-f0-9]{64}$' -or
     $env:CONDITIONS_FINGERPRINT -cnotmatch '^[a-f0-9]{64}$')) {
    throw 'Development admission digests are missing or malformed'
}
$bundleGraphDir = Join-Path $source 'apps/desktop/.hermes-bundle-graph'
if ($development) {
    if ($env:PACKAGE_VERSION -cnotmatch '^0\.0\.0-alpha\.dev\.[1-9][0-9]*-r[1-9][0-9]*$') {
        throw 'Development release identity mismatch'
    }
    python "$source/scripts/bundles/desktop.py" --commit $commit --variant light -- --dir
} else {
    $versionMatch = [regex]::Match($env:PACKAGE_VERSION, '^([0-9]+\.[0-9]+\.[0-9]+)-r[1-9][0-9]*$')
    $upstreamTag = $env:UPSTREAM_TAG
    if (!$versionMatch.Success -or $upstreamTag -cne "v$($versionMatch.Groups[1].Value)") {
        throw 'Stable release identity mismatch'
    }
    $tagCommit = (git -C $source rev-parse "refs/tags/$upstreamTag^{commit}").Trim()
    if ($tagCommit -cne $commit) {
        throw 'Upstream stable tag does not point to the pinned commit'
    }
    python "$source/scripts/bundles/desktop.py" --tag $upstreamTag --variant light -- --dir
}
$sourceRef = if ($development) { $commit } else { $upstreamTag }
$pack = Join-Path $source 'apps/desktop/release/win-unpacked'
if (!(Test-Path $pack)) { throw 'No unpacked Windows application was built' }
$stamp = Get-Content "$pack/resources/install-stamp.json" -Raw | ConvertFrom-Json
if ($stamp.payload -cne 'light' -or $stamp.commit -cne $commit -or $stamp.updateMechanism -cne 'external') {
    throw 'Wrong payload, provenance, or update owner'
}
if (Test-Path "$pack/resources/agent-payload") { throw 'Light unexpectedly contains a local agent' }
$bucket = Join-Path $root 'bucket'
$prepared = Get-Content "$source/.build/desktop-job/prepared.json" -Raw | ConvertFrom-Json
& $prepared.node "$bucket/scripts/hermes-desktop-light-bundle-graph.mjs" $source $bundleGraphDir $pack
$repository = $env:GITHUB_REPOSITORY
$runUrl = "https://github.com/$repository/actions/runs/$env:GITHUB_RUN_ID"
$bucketCommit = (git -C $bucket rev-parse HEAD).Trim()
$noticeMetadata = & python "$bucket/scripts/hermes-desktop-light-notices.py" `
    --source $source `
    --pack $pack `
    --source-ref $env:SOURCE_REF `
    --commit $commit `
    --bucket-repository $repository `
    --bucket-commit $bucketCommit `
    --run-url $runUrl | ConvertFrom-Json
$exeName = 'Hermes Light.exe'
if ($development) { $exeName = "hermes-light-$($commit.Substring(0, 7)).exe" }
$exe = Get-Item (Join-Path $pack $exeName)
# Use the exact managed Node admitted by upstream preparation.
& $prepared.node "$root/bucket/scripts/smoke-hermes-desktop-light.cjs" $source $exe.FullName $out
$version = $env:PACKAGE_VERSION
if ($development) {
    $name = "hermes-desktop-light-dev-$version-$commit-windows-x64.zip"
} else {
    $name = "hermes-desktop-light-$version-windows-x64.zip"
}
Compress-Archive -Path "$pack/*" -DestinationPath "$out/$name" -CompressionLevel Optimal
$receipt = @{
    schema = 1
    upstream = 'NousResearch/hermes-agent'
    sourceRef = $sourceRef
    commit = $commit
    version = $version
    preview = $false
    development = $development
    channel = if ($development) { 'development' } else { 'stable' }
    artifact = $name
    sha256 = (Get-FileHash "$out/$name" -Algorithm SHA256).Hash.ToLowerInvariant()
    payload = $stamp.payload
    updateMechanism = $stamp.updateMechanism
    executable = $exe.Name
    smoke = 'two native launches; renderer loaded; localStorage retained'
    nativeChecks = Get-Content "$out/native-checks.json" -Raw | ConvertFrom-Json
    notices = $noticeMetadata
    signing = 'unsigned unofficial build'
    licenseSha256 = $env:LICENSE_SHA256
    conditionsFingerprint = $env:CONDITIONS_FINGERPRINT
    run = "https://github.com/$env:GITHUB_REPOSITORY/actions/runs/$env:GITHUB_RUN_ID"
}
$receipt | ConvertTo-Json -Depth 10 | Set-Content "$out/provenance.json" -Encoding utf8NoBOM
