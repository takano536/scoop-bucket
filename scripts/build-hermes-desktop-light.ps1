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
$channel = $env:UPSTREAM_CHANNEL
if ($channel -cnotin @('canary', 'stable')) {
    throw 'Desktop release channel is not an official Desktop channel'
}
if ($env:PACKAGE_VERSION -notmatch '^\d+\.\d+\.\d+\.\d+(?:-alpha\.dev\.1)?-r[1-9][0-9]*$') {
    throw 'Desktop-release package identity mismatch'
}
if ($channel -ceq 'canary' -and $env:PACKAGE_VERSION -notmatch '-alpha\.dev\.1-') {
    throw 'Canary Desktop release package identity is missing its channel marker'
}
if ($channel -ceq 'stable' -and $env:PACKAGE_VERSION -match '-alpha\.dev\.1-') {
    throw 'Stable Desktop release package identity carries a canary marker'
}
$upstreamTag = $env:UPSTREAM_TAG
$upstreamSourceTag = $env:UPSTREAM_SOURCE_TAG
if ($channel -ceq 'canary') {
    if ($upstreamTag -notmatch '^v[^+\s]+\+canary\.20\d{6}T\d{6}Z$') {
        throw 'Desktop release source tag is not an official canary tag'
    }
    if ($upstreamSourceTag -cne $upstreamTag) {
        throw 'Canary Desktop build tag and source tag must be the same immutable tag'
    }
} else {
    if ($upstreamSourceTag -notmatch '^v\d+\.\d+\.\d+$') {
        throw 'Stable Desktop build needs an official release tag as its source tag'
    }
    if ($upstreamTag -ceq $upstreamSourceTag) {
        # A stable bundle archived directly under the release tag.
    } elseif ($upstreamTag -notmatch "^rc\.[1-9][0-9]*-$([regex]::Escape($upstreamSourceTag))$") {
        throw 'Stable Desktop build tag does not belong to the admitted release tag'
    }
}
$tagCommit = (git -C $source rev-parse "refs/tags/$upstreamSourceTag^{commit}").Trim()
if ($tagCommit -cne $commit) {
    throw 'Official Desktop release tag does not point to the admitted commit'
}
$desktopVersion = $env:DESKTOP_VERSION
if ($desktopVersion -notmatch '^\d+\.\d+\.\d+\.\d+$') {
    throw 'Official Desktop product version is malformed'
}
$bundleGraphDir = Join-Path $source 'apps/desktop/.hermes-bundle-graph'
python "$source/scripts/bundles/desktop.py" --tag $upstreamSourceTag --variant light -- --dir
$prepared = Get-Content "$source/.build/desktop-job/prepared.json" -Raw | ConvertFrom-Json
$pack = Join-Path $source 'apps/desktop/release/win-unpacked'
if (!(Test-Path $pack)) { throw 'No unpacked Windows application was built' }
$stamp = Get-Content "$pack/resources/install-stamp.json" -Raw | ConvertFrom-Json
if ($stamp.payload -cne 'light' -or $stamp.commit -cne $commit -or $stamp.tag -cne $upstreamSourceTag -or $stamp.updateMechanism -cne 'external') {
    throw 'Wrong payload, provenance, tag, or update owner'
}
if (Test-Path "$pack/resources/agent-payload") { throw 'Light unexpectedly contains a local agent' }
$bucket = Join-Path $root 'bucket'
& $prepared.node "$bucket/scripts/hermes-desktop-light-bundle-graph.mjs" $source $bundleGraphDir $pack
$repository = $env:GITHUB_REPOSITORY
$runUrl = "https://github.com/$env:GITHUB_REPOSITORY/actions/runs/$env:GITHUB_RUN_ID"
$bucketCommit = (git -C $bucket rev-parse HEAD).Trim()
$noticeMetadata = & python "$bucket/scripts/hermes-desktop-light-notices.py" `
    --source $source `
    --pack $pack `
    --source-ref $upstreamSourceTag `
    --commit $commit `
    --bucket-repository $repository `
    --bucket-commit $bucketCommit `
    --run-url $runUrl | ConvertFrom-Json
# The packaged Light executable is the official product identity for the
# admitted tag.  Resolve it from the exact source so a channel whose identity
# drifted fails here instead of publishing a manifest for a missing file.
$identityExe = [string](& $prepared.node -e "process.env.HERMES_DESKTOP_VARIANT='light';process.env.HERMES_BUILD_COMMIT='';process.env.HERMES_PAYLOAD_TAG=process.argv[2];process.stdout.write(String(require(process.argv[1]).windowsExecutableName))" (Join-Path $source 'apps/desktop/product-identity.cjs') $upstreamSourceTag).Trim()
$expectedExe = if ($channel -ceq 'canary') { 'hermes-light-canary.exe' } else { 'Hermes Light.exe' }
if ("$identityExe.exe" -cne $expectedExe) {
    throw "Desktop Light identity executable $identityExe.exe does not match the $channel channel contract $expectedExe"
}
$exeName = $expectedExe
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
    desktopTag = $upstreamTag
    desktopSourceTag = $upstreamSourceTag
    upstreamChannel = $channel
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
