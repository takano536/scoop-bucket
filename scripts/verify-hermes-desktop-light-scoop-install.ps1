[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BucketRoot,
    [Parameter(Mandatory = $true)]
    [string]$UpstreamDirectory,
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedVersion,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedCommit,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedHash,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedUrl
)

$ErrorActionPreference = 'Stop'
$BucketRoot = (Resolve-Path -LiteralPath $BucketRoot).Path
$UpstreamDirectory = (Resolve-Path -LiteralPath $UpstreamDirectory).Path
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

$repo = 'takano536/scoop-bucket'
$alias = 'takano536-verify'
$appName = 'hermes-desktop-light'
$expectedExeName = "hermes-light-$($ExpectedCommit.Substring(0, 7)).exe"
$expectedShortcutName = 'Hermes Desktop Light (Development).lnk'
$evidence = [ordered]@{
    schema = 1
    status = 'failed'
    runner = 'GitHub-hosted windows-latest; this is not a clean general Windows environment.'
    repository = $repo
    bucketAlias = $alias
    app = $appName
    expected = [ordered]@{
        version = $ExpectedVersion
        commit = $ExpectedCommit
        hash = $ExpectedHash
        url = $ExpectedUrl
        executable = $expectedExeName
    }
}
$appProcess = $null
$gatewayProcess = $null
$secret = $null

function Write-EvidenceJson {
    param(
        [Parameter(Mandatory = $true)] [string]$Path,
        [Parameter(Mandatory = $true)] [object]$Value
    )
    $Value | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $Path -Encoding utf8NoBOM
}

function Invoke-CapturedScoop {
    param(
        [Parameter(Mandatory = $true)] [string]$Name,
        [Parameter(Mandatory = $true)] [string[]]$Arguments
    )
    $output = @(& scoop @Arguments 2>&1 | ForEach-Object { [string]$_ })
    $exitCode = $LASTEXITCODE
    $text = $output -join "`n"
    Set-Content -LiteralPath (Join-Path $OutputDirectory "$Name.log") -Value $text -Encoding utf8NoBOM
    if ($exitCode -ne 0) {
        throw "scoop $($Arguments -join ' ') failed with exit code $exitCode"
    }
    return $text
}

function Wait-Http {
    param(
        [Parameter(Mandatory = $true)] [string]$Uri,
        [int]$TimeoutSeconds = 120
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Timed out waiting for $Uri"
}

function Stop-VerificationProcesses {
    if ($appProcess -and !$appProcess.HasExited) {
        Stop-Process -Id $appProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($gatewayProcess -and !$gatewayProcess.HasExited) {
        Stop-Process -Id $gatewayProcess.Id -Force -ErrorAction SilentlyContinue
    }
}

function Add-Summary {
    param([Parameter(Mandatory = $true)] [string]$Text)
    Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Value $Text -Encoding utf8NoBOM
}

try {
    $scoopRoot = Join-Path $env:USERPROFILE 'scoop'
    $env:PATH = "$(Join-Path $scoopRoot 'shims');$env:PATH"
    if (!(Get-Command scoop -ErrorAction SilentlyContinue)) {
        throw 'Scoop is not available after the official non-admin installer step'
    }

    Invoke-CapturedScoop -Name 'scoop-bucket-add' -Arguments @('bucket', 'add', $alias, "https://github.com/$repo") | Out-Null
    $installOutput = Invoke-CapturedScoop -Name 'scoop-install' -Arguments @('install', "$alias/$appName")
    $listOutput = Invoke-CapturedScoop -Name 'scoop-list' -Arguments @('list')
    $infoOutput = Invoke-CapturedScoop -Name 'scoop-info' -Arguments @('info', "$alias/$appName")

    $bucketManifestPath = Join-Path $scoopRoot "buckets\$alias\bucket\$appName.json"
    if (!(Test-Path -LiteralPath $bucketManifestPath)) {
        throw "Public bucket manifest was not installed: $bucketManifestPath"
    }
    $manifest = Get-Content -LiteralPath $bucketManifestPath -Raw | ConvertFrom-Json
    if ($manifest.version -ne $ExpectedVersion) {
        throw "Public bucket manifest version was $($manifest.version), expected $ExpectedVersion"
    }
    $manifestUrl = [string]$manifest.architecture.'64bit'.url
    $manifestHash = [string]$manifest.architecture.'64bit'.hash
    if ($manifestUrl -ne $ExpectedUrl -or $manifestHash -ne $ExpectedHash) {
        throw 'Public bucket manifest URL or hash does not match the published release'
    }
    $scoopOutput = $installOutput + "`n" + $infoOutput
    $urlObserved = @($ExpectedUrl, $ExpectedUrl.Replace('%2F', '/')) |
        Where-Object { $scoopOutput.Contains($_) } |
        Select-Object -First 1
    if (!$urlObserved) {
        throw 'Scoop install/info output did not identify the expected published release URL'
    }

    $cacheRoot = Join-Path $scoopRoot 'cache'
    $cacheFiles = @(Get-ChildItem -LiteralPath $cacheRoot -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "$appName*" } |
        Sort-Object LastWriteTimeUtc -Descending)
    if ($cacheFiles.Count -eq 0) {
        throw 'Scoop cache contains no downloaded Hermes Desktop Light archive'
    }
    $cacheFile = $cacheFiles[0]
    $cacheHash = (Get-FileHash -LiteralPath $cacheFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($cacheHash -ne $ExpectedHash) {
        throw "Scoop cache archive hash $cacheHash does not match published hash $ExpectedHash"
    }

    $appRoot = Join-Path $scoopRoot "apps\$appName"
    $currentPath = Join-Path $appRoot 'current'
    if (!(Test-Path -LiteralPath $currentPath)) {
        throw "Scoop current junction is missing: $currentPath"
    }
    $currentTarget = (Resolve-Path -LiteralPath $currentPath).Path
    $currentVersion = Split-Path -Leaf $currentTarget
    $prefix = (Invoke-CapturedScoop -Name 'scoop-prefix' -Arguments @('prefix', $appName)).Trim()
    $prefixResolved = (Resolve-Path -LiteralPath $prefix).Path
    if ($prefixResolved -ne $currentTarget) {
        throw "scoop prefix $prefixResolved does not equal current target $currentTarget"
    }
    if ($currentVersion -ne $ExpectedVersion) {
        throw "Scoop current target version was $currentVersion, expected $ExpectedVersion"
    }

    $exePath = Join-Path $currentTarget $expectedExeName
    if (!(Test-Path -LiteralPath $exePath -PathType Leaf)) {
        throw "Installed executable is missing: $exePath"
    }
    $shortcutPath = Join-Path ([Environment]::GetFolderPath('StartMenu')) "Programs\Scoop Apps\$expectedShortcutName"
    if (!(Test-Path -LiteralPath $shortcutPath -PathType Leaf)) {
        throw "Scoop Start-menu shortcut is missing: $shortcutPath"
    }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcutTarget = [Environment]::ExpandEnvironmentVariables([string]$shortcut.TargetPath)
    $shortcutTarget = (Resolve-Path -LiteralPath $shortcutTarget).Path
    $expectedExePath = (Resolve-Path -LiteralPath $exePath).Path
    if ($shortcutTarget -ne $expectedExePath) {
        throw "Shortcut target $shortcutTarget does not match installed executable $expectedExePath"
    }

    $binaries = @(Get-ChildItem -LiteralPath $currentTarget -File -Recurse -Force |
        Where-Object { $_.Extension.ToLowerInvariant() -in @('.exe', '.dll', '.node') } |
        Sort-Object FullName)
    $authenticode = @(
        foreach ($file in $binaries) {
            try {
                $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
                [ordered]@{
                    path = [IO.Path]::GetRelativePath($currentTarget, $file.FullName)
                    status = [string]$signature.Status
                    signer = if ($signature.SignerCertificate) { [string]$signature.SignerCertificate.Subject } else { $null }
                    thumbprint = if ($signature.SignerCertificate) { [string]$signature.SignerCertificate.Thumbprint } else { $null }
                }
            } catch {
                [ordered]@{
                    path = [IO.Path]::GetRelativePath($currentTarget, $file.FullName)
                    status = 'Error'
                    signer = $null
                    thumbprint = $null
                    error = $_.Exception.Message
                }
            }
        }
    )
    Write-EvidenceJson -Path (Join-Path $OutputDirectory 'authenticode.json') -Value ([ordered]@{
        schema = 1
        generatedBy = 'Get-AuthenticodeSignature'
        files = $authenticode
        statusCounts = @($authenticode | Group-Object status | ForEach-Object { [ordered]@{ status = $_.Name; count = $_.Count } })
    })

    $gatewayHome = Join-Path $env:RUNNER_TEMP 'hermes-scoop-install-gateway-home'
    $hermesHome = Join-Path $env:RUNNER_TEMP 'hermes-scoop-install-hermes-home'
    $userData = Join-Path $env:RUNNER_TEMP 'hermes-scoop-install-user-data'
    $gatewayLog = Join-Path $env:RUNNER_TEMP 'hermes-scoop-install-gateway.log'
    $gatewayErrorLog = Join-Path $env:RUNNER_TEMP 'hermes-scoop-install-gateway-error.log'
    New-Item -ItemType Directory -Force -Path $gatewayHome, $hermesHome, $userData | Out-Null
    $secretBytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Fill($secretBytes)
    $secret = [Convert]::ToBase64String($secretBytes)
    Write-Output "::add-mask::$secret"
    $wrongSecret = "$secret-wrong"
    $gatewayPort = Get-Random -Minimum 22000 -Maximum 32000
    $cdpPort = Get-Random -Minimum 43000 -Maximum 50000
    $python = (Get-Command python -ErrorAction Stop).Source
    $env:HERMES_DASHBOARD_SESSION_TOKEN = $secret
    $env:HERMES_DESKTOP = '1'
    foreach ($name in @('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'XAI_API_KEY', 'GEMINI_API_KEY', 'HF_TOKEN', 'HUGGINGFACE_TOKEN')) {
        Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    }
    $env:HERMES_HOME = $gatewayHome
    $gatewayProcess = Start-Process -FilePath $python -ArgumentList @('-m', 'hermes_cli.main', 'serve', '--host', '127.0.0.1', "--port=$gatewayPort", '--skip-build') -WorkingDirectory $UpstreamDirectory -RedirectStandardOutput $gatewayLog -RedirectStandardError $gatewayErrorLog -PassThru -WindowStyle Hidden
    Wait-Http -Uri "http://127.0.0.1:$gatewayPort/api/status"
    $env:HERMES_HOME = $hermesHome
    $env:HERMES_DESKTOP_USER_DATA_DIR = $userData
    $savedPath = $env:PATH
    try {
        $env:PATH = "$currentTarget;$env:SystemRoot\System32;$env:SystemRoot"
        $appProcess = Start-Process -FilePath $exePath -ArgumentList @("--remote-debugging-port=$cdpPort") -WorkingDirectory $currentTarget -PassThru -WindowStyle Hidden
    } finally {
        $env:PATH = $savedPath
    }
    $launchResultPath = Join-Path $OutputDirectory 'launch-evidence.json'
    $acceptanceJs = Join-Path $BucketRoot 'scripts/accept-hermes-desktop-light.cjs'
    & node $acceptanceJs --phase before --cdp-port $cdpPort --app-root $currentTarget --gateway-url "http://127.0.0.1:$gatewayPort" --secret $secret --wrong-secret $wrongSecret --result $launchResultPath --preview
    if ($LASTEXITCODE -ne 0) {
        throw "Existing Electron acceptance driver failed with exit code $LASTEXITCODE"
    }
    $launch = Get-Content -LiteralPath $launchResultPath -Raw | ConvertFrom-Json
    if ($launch.status -ne 'passed' -or $launch.gateway.authenticated -ne $true -or $launch.updater.check.reason -ne 'commit-build') {
        throw 'Installed app launch evidence did not prove gateway authentication and commit-build external updater behavior'
    }

    $evidence.install = [ordered]@{
        version = $currentVersion
        prefix = $prefixResolved
        currentPath = $currentPath
        currentTarget = $currentTarget
        executable = $expectedExePath
        shortcut = $shortcutPath
        shortcutTarget = $shortcutTarget
        manifestUrl = $manifestUrl
        manifestHash = $manifestHash
        cacheFile = $cacheFile.FullName
        cacheHash = $cacheHash
        installOutputContainsExpectedUrl = ($installOutput + "`n" + $infoOutput).Contains($ExpectedUrl)
        hashVerifiedFromCache = $cacheHash -eq $ExpectedHash
    }
    $evidence.authenticode = Get-Content -LiteralPath (Join-Path $OutputDirectory 'authenticode.json') -Raw | ConvertFrom-Json
    $evidence.launch = $launch
    $evidence.status = 'passed'
    Write-EvidenceJson -Path (Join-Path $OutputDirectory 'scoop-install-evidence.json') -Value $evidence

    $rows = @(
        '| File | Authenticode status | Signer |',
        '| --- | --- | --- |'
    )
    foreach ($item in $authenticode) {
        $signer = if ($item.signer) { ([string]$item.signer).Replace('|', '\|') } else { 'Not signed' }
        $rows += "| $($item.path.Replace('|', '\|')) | $($item.status) | $signer |"
    }
    Add-Summary @"
## Hermes Desktop Light public Scoop install

- Status: **passed**
- Bucket: `$alias` from `https://github.com/$repo`
- Version: `$currentVersion`
- Prefix: `$prefixResolved`
- `current` target: `$currentTarget`
- Executable: `$expectedExePath`
- Start-menu shortcut target: `$shortcutTarget`
- Published URL/hash: `$manifestUrl` / `$manifestHash`
- Scoop cache SHA256: `$cacheHash`
- GitHub-hosted `windows-latest` runner evidence is **not** a guarantee for a clean general Windows installation.

### Authenticode

$($rows -join "`n")
"@
} catch {
    $evidence.error = $_.Exception.Message
    Write-EvidenceJson -Path (Join-Path $OutputDirectory 'scoop-install-evidence.json') -Value $evidence
    Add-Summary @"
## Hermes Desktop Light public Scoop install

- Status: **failed**
- GitHub-hosted `windows-latest` runner evidence is **not** a guarantee for a clean general Windows installation.
- Error: `$($_.Exception.Message)`
"@
    throw
} finally {
    Stop-VerificationProcesses
    if ($secret) {
        Remove-Item Env:HERMES_DASHBOARD_SESSION_TOKEN -ErrorAction SilentlyContinue
    }
}
