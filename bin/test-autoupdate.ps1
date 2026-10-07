<#
Validate the actual Scoop update path without installing apps or publishing changes.
Only disposable manifest copies are updated. Installer/uninstaller hooks are never run.
#>
param(
    [Parameter(Mandatory)][string]$ScoopHome,
    [string]$BucketDir = "$PSScriptRoot/../bucket"
)
$ErrorActionPreference = 'Stop'
$ScoopHome = (Resolve-Path $ScoopHome).Path
$files = @(Get-ChildItem -LiteralPath $BucketDir -Filter '*.json' -File)
if (!$files.Count) {
    Write-Warning 'No real manifests found; live autoupdate validation has NOT run.'
    if ($env:GITHUB_STEP_SUMMARY) {
        '### Autoupdate: no real manifests found (live checks not run)' | Add-Content $env:GITHUB_STEP_SUMMARY
    }
    return
}
$work = Join-Path ([IO.Path]::GetTempPath()) ('scoop-autoupdate-' + [guid]::NewGuid())
New-Item $work -ItemType Directory | Out-Null
$failures = @()
try {
    . "$ScoopHome/lib/core.ps1"
    . "$ScoopHome/lib/manifest.ps1"
    foreach ($file in $files) {
        try {
            Write-Host "Validating $($file.Name)"
            $original = Get-Content $file.FullName -Raw | ConvertFrom-Json
            if (!$original.checkver) { throw 'Missing checkver: Excavator would silently skip this manifest.' }
            if (!$original.autoupdate) { throw 'Missing autoupdate: version detection cannot update this manifest.' }
            $arches = if ($original.architecture) { @($original.architecture.PSObject.Properties.Name) } else { @('64bit') }
            foreach ($arch in $arches) {
                if (!(arch_specific 'url' $original.autoupdate $arch)) { throw "Missing autoupdate.url for $arch" }
                foreach ($property in @('url', 'extract_dir')) {
                    foreach ($template in @(arch_specific $property $original.autoupdate $arch)) {
                        if ([string]$template -like "*$($original.version)*" -and [string]$template -notmatch '\$(?:\w*Version|version|match\w*)') {
                            throw "Fixed version in autoupdate.$property for ${arch}: $template"
                        }
                    }
                }
            }
            $dir = Join-Path $work $file.BaseName
            New-Item $dir -ItemType Directory | Out-Null
            $copy = Join-Path $dir $file.Name
            # A sentinel forces a real manifest write even when upstream is already current.
            # Do NOT use -Version: it would bypass the checkver parsing being tested.
            $candidate = Get-Content $file.FullName -Raw | ConvertFrom-Json
            $candidate.version = '0.0.0-autoupdate-test'
            $candidate | ConvertTo-Json -Depth 100 | Set-Content $copy -Encoding utf8
            & "$ScoopHome/bin/checkver.ps1" -App $file.BaseName -Dir $dir -ForceUpdate -ThrowError
            $updated = Get-Content $copy -Raw | ConvertFrom-Json
            if ($updated.version -eq $candidate.version) {
                throw 'checkver did not produce an updated manifest (download, regex or version extraction failure).'
            }
            foreach ($arch in $arches) {
                $urls = @(arch_specific 'url' $updated $arch)
                $hashes = @(arch_specific 'hash' $updated $arch)
                $extractDirs = @(arch_specific 'extract_dir' $updated $arch)
                if (!$urls.Count -or $urls.Count -ne $hashes.Count) { throw "URL/hash count mismatch for $arch" }
                # Same-version regeneration must reproduce the published manifest.
                if ($updated.version -eq $original.version) {
                    foreach ($property in @('url', 'hash', 'extract_dir')) {
                        $before = ConvertTo-Json -InputObject ([string[]]@(arch_specific $property $original $arch)) -Compress
                        $after = ConvertTo-Json -InputObject ([string[]]@(arch_specific $property $updated $arch)) -Compress
                        if ($before -cne $after) { throw "Current $property disagrees with autoupdate for ${arch}: $before vs $after" }
                    }
                }
                for ($i = 0; $i -lt $urls.Count; $i++) {
                    $url = [string]$urls[$i]
                    $hash = [string]$hashes[$i]
                    if ($url -match '\$[A-Za-z_]' -or $url -notmatch '^https?://') { throw "Invalid/unresolved URL: $url" }
                    if ($hash -notmatch '^(?:(md5|sha1|sha512):)?[a-fA-F0-9]+$') { throw "Invalid hash: $hash" }
                    $algorithm = 'SHA256'
                    $expected = $hash
                    if ($hash.Contains(':')) { $algorithm, $expected = $hash.Split(':', 2) }
                    $artifact = Join-Path $dir "$arch-$i.download"
                    # Download independently: a checksum API alone does not establish artifact availability.
                    Invoke-WebRequest -Uri ($url.Split('#')[0]) -OutFile $artifact -TimeoutSec 120
                    $actual = (Get-FileHash $artifact -Algorithm $algorithm).Hash
                    if ($actual -ine $expected) { throw "Downloaded hash mismatch for $url" }
                    if ($extractDirs.Count) {
                        $extractDir = [string]$extractDirs[[Math]::Min($i, $extractDirs.Count - 1)]
                        if ($extractDir -match '\$[A-Za-z_]' -or [IO.Path]::IsPathRooted($extractDir) -or $extractDir -match '(^|[\\/])\.\.([\\/]|$)') {
                            throw "Invalid/unresolved extract_dir: $extractDir"
                        }
                        $destination = Join-Path $dir "$arch-$i-extracted"
                        & 7z x $artifact "-o$destination" -y | Out-Host
                        if ($LASTEXITCODE -ne 0) { throw "Archive extraction failed for $url" }
                        if (!(Test-Path (Join-Path $destination $extractDir) -PathType Container)) {
                            throw "extract_dir does not exist in downloaded archive: $extractDir"
                        }
                    }
                }
            }
            Write-Host "PASS $($file.BaseName): detected $($updated.version), regenerated and verified artifacts"
            if ($env:GITHUB_STEP_SUMMARY) {
                "- PASS $($file.BaseName): $($updated.version)" | Add-Content $env:GITHUB_STEP_SUMMARY
            }
        } catch {
            $failures += "$($file.Name): $($_.Exception.Message)"
            Write-Warning $failures[-1]
        }
    }
    if ($failures.Count) { throw ($failures -join "`n") }
} finally {
    Remove-Item $work -Recurse -Force
}
