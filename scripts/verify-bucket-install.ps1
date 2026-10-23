#Requires -Version 5.1
<#
.SYNOPSIS
    bucket/ の全manifestを実際にScoopでinstallし、配布物を取得できるか確認する。
.DESCRIPTION
    Windows専用の検証入口。作業ツリーの bucket/ をScoopの専用ローカルbucketへコピーし、
    各アプリを scoop install して、URL・hash・extract_dir・installerが実際に通ることを
    確認する。bucket/ とmanifestは変更しない。結果はJSONとMarkdownで出力する。
    Scoopが動作しない環境（Linuxなど）では実行できない。
.PARAMETER BucketRoot
    リポジトリのルート。既定はこのスクリプトの親ディレクトリ。
.PARAMETER OutputDirectory
    ログと集計の出力先。既定は <repo>/artifacts/bucket-install。
.PARAMETER App
    対象アプリ名を限定する。省略すると bucket/ の全manifestが対象。
.PARAMETER SkipApp
    環境依存などでinstall対象から外すアプリ名。
.PARAMETER KeepInstalled
    検証後にアプリをuninstallしない。
.PARAMETER KeepBucket
    検証用に追加したローカルbucketを残す。
.EXAMPLE
    pwsh ./scripts/verify-bucket-install.ps1 -Verbose
#>
[CmdletBinding()]
param(
    [string]$BucketRoot = (Join-Path $PSScriptRoot '..'),
    [string]$OutputDirectory = '',
    [string[]]$App,
    [string[]]$SkipApp = @(),
    [switch]$KeepInstalled,
    [switch]$KeepBucket
)

$ErrorActionPreference = 'Stop'

function Set-Utf8File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value
    )
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Path, $Value, $encoding)
}

function Invoke-ScoopLog {
    param(
        [Parameter(Mandatory = $true)][string]$LogPath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $lines = @(& scoop @Arguments 2>&1 | ForEach-Object { [string]$_ })
    $exitCode = $LASTEXITCODE
    Set-Utf8File -Path $LogPath -Value ($lines -join "`r`n")
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output   = $lines
    }
}

$BucketRoot = (Resolve-Path -LiteralPath $BucketRoot).Path
$manifestsRoot = Join-Path $BucketRoot 'bucket'
if (-not (Test-Path -LiteralPath $manifestsRoot -PathType Container)) {
    throw "bucket directory was not found: $manifestsRoot"
}

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $BucketRoot 'artifacts/bucket-install'
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

if (-not (Get-Command scoop -ErrorAction SilentlyContinue)) {
    throw 'scoop was not found on PATH. This verification is Windows-only; install Scoop first (https://scoop.sh).'
}

$scoopRoot = if ($env:SCOOP) { $env:SCOOP } else { Join-Path $env:USERPROFILE 'scoop' }
$bucketsRoot = Join-Path $scoopRoot 'buckets'
if (-not (Test-Path -LiteralPath $bucketsRoot -PathType Container)) {
    throw "Scoop buckets directory was not found: $bucketsRoot"
}

$manifests = @(Get-ChildItem -LiteralPath $manifestsRoot -Filter '*.json' -File | Sort-Object -Property Name)
if ($manifests.Count -eq 0) {
    throw "No manifest was found in $manifestsRoot"
}

$names = @($manifests | ForEach-Object { $_.BaseName })
if ($App) {
    $unknown = @($App | Where-Object { $names -notcontains $_ })
    if ($unknown.Count -gt 0) {
        throw "Not found in bucket/: $($unknown -join ', ')"
    }
    $names = @($App)
}
$names = @($names | Where-Object { $SkipApp -notcontains $_ } | Sort-Object)
if ($names.Count -eq 0) {
    throw 'No manifest left to verify.'
}

# 検証用のbucketは作業ツリーのコピーとして追加する。git管理下にしないため、
# scoop update がこのbucketを更新することはなく、検証対象のmanifestだけを読む。
$alias = 'verify-install-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
$aliasDir = Join-Path $bucketsRoot $alias
New-Item -ItemType Directory -Path $aliasDir -Force | Out-Null
Copy-Item -Path (Join-Path $manifestsRoot '*.json') -Destination $aliasDir -Force

Write-Host "Verifying $($names.Count) manifest(s) from $manifestsRoot"
Write-Host "Scoop bucket alias: $alias ($aliasDir)"

$results = New-Object System.Collections.ArrayList
try {
    foreach ($name in $names) {
        $appOutput = Join-Path $OutputDirectory $name
        New-Item -ItemType Directory -Force -Path $appOutput | Out-Null
        $started = Get-Date
        $manifest = Get-Content -LiteralPath (Join-Path $manifestsRoot "$name.json") -Raw | ConvertFrom-Json
        $status = 'failed'
        $detail = ''
        Write-Host "--- $name (version $($manifest.version))"

        $install = Invoke-ScoopLog -LogPath (Join-Path $appOutput 'install.log') -Arguments @('install', "$alias/$name")
        if ($install.ExitCode -ne 0) {
            $detail = "scoop install exited with code $($install.ExitCode)"
        }
        else {
            $prefix = Invoke-ScoopLog -LogPath (Join-Path $appOutput 'prefix.log') -Arguments @('prefix', $name)
            $prefixPath = [string](@($prefix.Output) | Where-Object { $_ } | Select-Object -Last 1)
            if ($prefix.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($prefixPath) -or -not (Test-Path -LiteralPath $prefixPath -PathType Container)) {
                $detail = 'scoop prefix did not resolve an installed app directory'
            }
            else {
                $status = 'installed'
            }
        }

        if (-not $KeepInstalled) {
            $uninstall = Invoke-ScoopLog -LogPath (Join-Path $appOutput 'uninstall.log') -Arguments @('uninstall', $name)
            if ($uninstall.ExitCode -ne 0 -and $status -eq 'installed') {
                Write-Warning "scoop uninstall $name exited with code $($uninstall.ExitCode); see $appOutput/uninstall.log"
            }
        }

        $seconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
        $null = $results.Add([ordered]@{
                app     = $name
                version = [string]$manifest.version
                status  = $status
                detail  = $detail
                seconds = $seconds
                log     = $appOutput
            })
        if ($status -eq 'installed') {
            Write-Host "    installed in $seconds s"
        }
        else {
            Write-Host "    FAILED: $detail"
        }
    }
}
finally {
    if (-not $KeepBucket) {
        Remove-Item -LiteralPath $aliasDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$failed = @($results | Where-Object { $_.status -ne 'installed' })

$evidence = [ordered]@{
    schema      = 1
    generatedAt = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    bucketRoot  = $BucketRoot
    bucketAlias = $alias
    runner      = [string]$env:RUNNER_NAME
    commit      = [string]$env:GITHUB_SHA
    apps        = @($results)
}
Set-Utf8File -Path (Join-Path $OutputDirectory 'summary.json') -Value (($evidence | ConvertTo-Json -Depth 10) -replace "`r`n", "`n")

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add('# bucket/ install verification')
$lines.Add('')
if ($failed.Count -eq 0) {
    $lines.Add("All $($results.Count) manifest(s) installed successfully.")
}
else {
    $lines.Add("$($failed.Count) of $($results.Count) manifest(s) failed to install.")
}
$lines.Add('')
$lines.Add('| app | version | result | seconds |')
$lines.Add('| --- | --- | --- | --- |')
foreach ($result in $results) {
    $lines.Add(('| {0} | {1} | {2} | {3} |' -f $result.app, $result.version, $result.status, $result.seconds))
}
if ($failed.Count -gt 0) {
    $lines.Add('')
    foreach ($result in $failed) {
        $lines.Add(("- ``$($result.app)``: $($result.detail) (see ``$($result.app)/install.log``)"))
    }
}
$lines.Add('')
Set-Utf8File -Path (Join-Path $OutputDirectory 'summary.md') -Value (($lines -join "`n") + "`n")

if ($failed.Count -gt 0) {
    Write-Host "FAILED: $((@($failed | ForEach-Object { $_.app })) -join ', ')"
    exit 1
}
Write-Host 'All manifests installed successfully.'
exit 0
