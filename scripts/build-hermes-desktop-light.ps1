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
    if ($env:PACKAGE_VERSION -cnotmatch '^([0-9]+\.[0-9]+\.[0-9]+)-r[1-9][0-9]*$' -or $env:SOURCE_REF -cne "v$($Matches[1])") { throw 'Release identity mismatch' }
    python "$source/scripts/bundles/desktop.py" --tag $env:SOURCE_REF --variant light -- --dir
}
$pack = Join-Path $source 'apps/desktop/release/win-unpacked'
if (!(Test-Path $pack)) { throw 'No unpacked Windows application was built' }
$stamp = Get-Content "$pack/resources/install-stamp.json" -Raw | ConvertFrom-Json
if ($stamp.payload -cne 'light' -or $stamp.commit -cne $commit -or $stamp.updateMechanism -cne 'external') {
    throw 'Wrong payload, provenance, or update owner'
}
if (Test-Path "$pack/resources/agent-payload") { throw 'Light unexpectedly contains a local agent' }
$bucket = Join-Path $root 'bucket'
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
if ($env:PREVIEW -eq 'true') { $exeName = "hermes-light-$($commit.Substring(0, 7)).exe" }
$exe = Get-Item (Join-Path $pack $exeName)
# Use the exact managed Node admitted by upstream preparation.
$prepared = Get-Content "$source/.build/desktop-job/prepared.json" -Raw | ConvertFrom-Json
& $prepared.node "$root/bucket/scripts/smoke-hermes-desktop-light.cjs" $source $exe.FullName $out
$version = $env:PACKAGE_VERSION
if ($env:PREVIEW -eq 'true') { $version = "preview-$($commit.Substring(0, 7))" }
$name = "hermes-desktop-light-$version-windows-x64.zip"
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
    executable = $exe.Name
    smoke = 'two native launches; renderer loaded; localStorage retained'
    nativeChecks = Get-Content "$out/native-checks.json" -Raw | ConvertFrom-Json
    notices = $noticeMetadata
    signing = 'unsigned unofficial build'
    run = "https://github.com/$env:GITHUB_REPOSITORY/actions/runs/$env:GITHUB_RUN_ID"
}
$receipt | ConvertTo-Json -Depth 10 | Set-Content "$out/provenance.json" -Encoding utf8NoBOM
