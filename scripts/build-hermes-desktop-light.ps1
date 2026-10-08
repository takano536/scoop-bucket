$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$root = (Get-Location).Path
$source = Join-Path $root 'upstream'
$out = Join-Path $root 'output'
New-Item -ItemType Directory -Path $out | Out-Null
$commit = (git -C $source rev-parse HEAD).Trim()
$bundleGraphDir = Join-Path $source 'apps/desktop/.hermes-bundle-graph'
New-Item -ItemType Directory -Path $bundleGraphDir -Force | Out-Null
$rendererBuildPath = Join-Path $source 'scripts/build/desktop.mjs'
$rendererBuild = Get-Content $rendererBuildPath -Raw
$rendererOriginal = $rendererBuild
$rendererMarker = 'build: { outDir: product, emptyOutDir: true },'
if (!$rendererBuild.Contains($rendererMarker)) { throw 'Upstream renderer build marker changed; refusing to build without source maps' }
$rendererBuild = $rendererBuild.Replace(
    $rendererMarker,
    'build: { outDir: product, emptyOutDir: true, sourcemap: true },'
)
Set-Content $rendererBuildPath -Value $rendererBuild -Encoding utf8NoBOM -NoNewline
$mainBundlePath = Join-Path $source 'apps/desktop/scripts/bundle-electron-main.mjs'
$mainBundle = Get-Content $mainBundlePath -Raw
$mainOriginal = $mainBundle
$commonMarker = '  const common = {'
if (!$mainBundle.Contains($commonMarker)) { throw 'Upstream Electron bundle marker changed; refusing to build without metafiles' }
$mainBundle = $mainBundle.Replace(
    $commonMarker,
    "  const metafileDir = process.env.HERMES_BUNDLE_METAFILE_DIR`n$commonMarker"
)
foreach ($entry in @(
    @{ Output = 'electron-main.mjs'; Metafile = 'electron-main.metafile.json' },
    @{ Output = 'electron-preload.js'; Metafile = 'electron-preload.metafile.json' },
    @{ Output = 'preview-guest-preload.js'; Metafile = 'preview-guest-preload.metafile.json' }
)) {
    $old = "    outfile: join(out, '$($entry.Output)'),"
    $new = "$old`n    metafile: Boolean(metafileDir),"
    if (!$mainBundle.Contains($old)) { throw "Upstream Electron bundle output marker changed: $($entry.Output)" }
    $mainBundle = $mainBundle.Replace($old, $new)
}
$importMarker = "import { mkdirSync, readFileSync } from 'node:fs'"
$importReplacement = "import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'"
if (!$mainBundle.Contains($importMarker)) { throw 'Upstream Electron bundle import marker changed; refusing to build with metafiles' }
$mainBundle = $mainBundle.Replace($importMarker, $importReplacement)
$buildMarker = "  await build({"
$first = $mainBundle.IndexOf($buildMarker)
if ($first -lt 0) { throw 'Upstream Electron main build marker changed' }
$mainBundle = $mainBundle.Substring(0, $first) + "  const mainResult = await build({" + $mainBundle.Substring($first + $buildMarker.Length)
$second = $mainBundle.IndexOf($buildMarker, $first + 1)
if ($second -lt 0) { throw 'Upstream Electron preload build marker changed' }
$firstClose = $mainBundle.LastIndexOf("  })", $second)
$mainBundle = $mainBundle.Substring(0, $firstClose + 4) + "`n  if (metafileDir && mainResult.metafile) writeFileSync(join(metafileDir, 'electron-main.metafile.json'), JSON.stringify(mainResult.metafile))" + $mainBundle.Substring($firstClose + 4)
$second = $mainBundle.IndexOf($buildMarker, $first + 1)
$mainBundle = $mainBundle.Substring(0, $second) + "  const preloadResult = await build({" + $mainBundle.Substring($second + $buildMarker.Length)
$third = $mainBundle.IndexOf($buildMarker, $second + 1)
if ($third -lt 0) { throw 'Upstream Electron preview preload build marker changed' }
$secondClose = $mainBundle.LastIndexOf("  })", $third)
$mainBundle = $mainBundle.Substring(0, $secondClose + 4) + "`n  if (metafileDir && preloadResult.metafile) writeFileSync(join(metafileDir, 'electron-preload.metafile.json'), JSON.stringify(preloadResult.metafile))" + $mainBundle.Substring($secondClose + 4)
$third = $mainBundle.IndexOf($buildMarker, $second + 1)
$mainBundle = $mainBundle.Substring(0, $third) + "  const guestResult = await build({" + $mainBundle.Substring($third + $buildMarker.Length)
$returnMarker = "  return { stampClock"
$returnAt = $mainBundle.IndexOf($returnMarker, $third + 1)
if ($returnAt -lt 0) { throw 'Upstream Electron bundle return marker changed' }
$thirdClose = $mainBundle.LastIndexOf("  })", $returnAt)
$mainBundle = $mainBundle.Substring(0, $thirdClose + 4) + "`n  if (metafileDir && guestResult.metafile) writeFileSync(join(metafileDir, 'preview-guest-preload.metafile.json'), JSON.stringify(guestResult.metafile))" + $mainBundle.Substring($thirdClose + 4)
Set-Content $mainBundlePath -Value $mainBundle -Encoding utf8NoBOM -NoNewline
$env:HERMES_BUNDLE_METAFILE_DIR = $bundleGraphDir
git -C $source update-index --assume-unchanged -- scripts/build/desktop.mjs apps/desktop/scripts/bundle-electron-main.mjs
try {
    if ($env:PREVIEW -eq 'true') {
        python "$source/scripts/bundles/desktop.py" --commit $commit --variant light -- --dir
    } else {
        if ($env:PACKAGE_VERSION -cnotmatch '^([0-9]+\.[0-9]+\.[0-9]+)-r[1-9][0-9]*$' -or $env:SOURCE_REF -cne "v$($Matches[1])") { throw 'Release identity mismatch' }
        python "$source/scripts/bundles/desktop.py" --tag $env:SOURCE_REF --variant light -- --dir
    }
} finally {
    Set-Content $rendererBuildPath -Value $rendererOriginal -Encoding utf8NoBOM -NoNewline
    Set-Content $mainBundlePath -Value $mainOriginal -Encoding utf8NoBOM -NoNewline
    git -C $source update-index --no-assume-unchanged -- scripts/build/desktop.mjs apps/desktop/scripts/bundle-electron-main.mjs
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
