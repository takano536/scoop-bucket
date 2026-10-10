$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$root = (Get-Location).Path
$source = Join-Path $root 'upstream'
$out = Join-Path $root 'output'
New-Item -ItemType Directory -Path $out | Out-Null
$commit = (git -C $source rev-parse HEAD).Trim()
if ($commit -notmatch '^[a-f0-9]{40}$' -or $env:SOURCE_REF -cne $commit) {
    throw 'Builder checkout is not the exact admitted upstream Desktop release commit'
}
if ($env:LICENSE_SHA256 -cnotmatch '^[a-f0-9]{64}$' -or
    $env:CONDITIONS_FINGERPRINT -cnotmatch '^[a-f0-9]{64}$') {
    throw 'Desktop-release admission digests are missing or malformed'
}
if ($env:PACKAGE_VERSION -notmatch '^\d+\.\d+\.\d+\.\d+-alpha\.dev\.1-r[1-9][0-9]*$') {
    throw 'Desktop-release package identity mismatch'
}
$upstreamTag = $env:UPSTREAM_TAG
if ($upstreamTag -notmatch '^v[^+\s]+\+canary\.20\d{6}T\d{6}Z$') {
    throw 'Desktop release source tag is not an official canary tag'
}
$tagCommit = (git -C $source rev-parse "refs/tags/$upstreamTag^{commit}").Trim()
if ($tagCommit -cne $commit) {
    throw 'Official Desktop release tag does not point to the admitted commit'
}
$desktopVersion = $env:DESKTOP_VERSION
if ($desktopVersion -notmatch '^\d+\.\d+\.\d+\.\d+$') {
    throw 'Official Desktop product version is malformed'
}
$bundleGraphDir = Join-Path $source 'apps/desktop/.hermes-bundle-graph'
python "$source/scripts/bundles/desktop.py" --tag $upstreamTag --variant light -- --dir
$prepared = Get-Content "$source/.build/desktop-job/prepared.json" -Raw | ConvertFrom-Json
$pack = Join-Path $source 'apps/desktop/release/win-unpacked'
if (!(Test-Path $pack)) { throw 'No unpacked Windows application was built' }
$stamp = Get-Content "$pack/resources/install-stamp.json" -Raw | ConvertFrom-Json
if ($stamp.payload -cne 'light' -or $stamp.commit -cne $commit -or $stamp.tag -cne $upstreamTag -or $stamp.updateMechanism -cne 'external') {
    throw 'Wrong payload, provenance, tag, or update owner'
}
if (Test-Path "$pack/resources/agent-payload") { throw 'Light unexpectedly contains a local agent' }
$bucket = Join-Path $root 'bucket'
& $prepared.node "$bucket/scripts/hermes-desktop-light-bundle-graph.mjs" $source $bundleGraphDir $pack
$runUrl = "https://github.com/$env:GITHUB_REPOSITORY/actions/runs/$env:GITHUB_RUN_ID"
$bucketCommit = (git -C $bucket rev-parse HEAD).Trim()
$noticeMetadata = & python "$bucket/scripts/hermes-desktop-light-notices.py" `
    --source $source `
    --pack $pack `
    --source-ref $upstreamTag `
    --commit $commit `
    --bucket-repository $repository `
    --bucket-commit $bucketCommit `
    --run-url $runUrl | ConvertFrom-Json
$exeName = 'hermes-light-canary.exe'
$exe = Get-Item (Join-Path $pack $exeName)
# Use the exact managed Node admitted by upstream preparation.
& $prepared.node "$root/bucket/scripts/smoke-hermes-desktop-light.cjs" $source $exe.FullName $out
$name = "hermes-desktop-light-$($env:PACKAGE_VERSION)-windows-x64.zip"
Compress-Archive -Path "$pack/*" -DestinationPath "$out/$name" -CompressionLevel Optimal
$receipt = @{
    schema = 2
    upstream = 'NousResearch/hermes-agent'
    sourceRef = $env:SOURCE_REF
    commit = $commit
    upstreamTag = $upstreamTag
    upstreamChannel = 'canary'
    desktopVersion = $desktopVersion
    desktopFeedUrl = $env:DESKTOP_FEED_URL
    desktopFeedEtag = $env:DESKTOP_FEED_ETAG
    desktopFeedLastModified = $env:DESKTOP_FEED_LAST_MODIFIED
    desktopArtifactUrl = $env:DESKTOP_ARTIFACT_URL
    desktopArtifactSha256 = $env:DESKTOP_ARTIFACT_SHA256
    version = $env:PACKAGE_VERSION
    preview = $false
    development = $true
    channel = 'desktop-release'
    distribution = 'unofficial-light'
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
    bucketCommit = $bucketCommit
    run = $runUrl
}
$receipt | ConvertTo-Json -Depth 10 | Set-Content "$out/provenance.json" -Encoding utf8NoBOM
