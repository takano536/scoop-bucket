[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ArtifactDirectory,
    [Parameter(Mandatory = $true)]
    [string]$UpstreamDirectory,
    [Parameter(Mandatory = $true)]
    [string]$PackageVersion,
    [Parameter(Mandatory = $true)]
    [string]$SourceRef,
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

$ArtifactDirectory = (Resolve-Path -LiteralPath $ArtifactDirectory).Path
$UpstreamDirectory = (Resolve-Path -LiteralPath $UpstreamDirectory).Path
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

$scratch = Join-Path $env:RUNNER_TEMP ("hermes-light-acceptance-{0}" -f ([guid]::NewGuid().ToString('N')))
New-Item -ItemType Directory -Force -Path $scratch | Out-Null
$manifestPath = Join-Path $scratch 'hermes-agent-light-acceptance.json'
$httpLog = Join-Path $scratch 'artifact-http.log'
$gatewayLog = Join-Path $scratch 'gateway.log'
$gatewayErrorLog = Join-Path $scratch 'gateway-error.log'
$httpProcess = $null
$gatewayProcess = $null
$failure = $null
$exitCode = 0
$secret = $null
$appName = 'hermes-agent-light-acceptance'
$shortcutName = 'Hermes Light Acceptance'
$zipPath = $null
$installedRoot = $null
$hermesHome = Join-Path $scratch 'hermes-home'
$userData = Join-Path $scratch 'desktop-user-data'
$gatewayHome = Join-Path $scratch 'gateway-home'

function Write-EvidenceJson {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [object]$Value
    )

    $Value | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $Path -Encoding utf8NoBOM
}

function Redact {
    param([AllowNull()][object]$Value)

    $text = [string]$Value
    if ($secret) {
        $text = $text.Replace($secret, '[REDACTED]')
    }
    return $text
}

function Invoke-Scoop {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & scoop @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "scoop $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Wait-Http {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri,
        [int]$TimeoutSeconds = 90
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $response
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Timed out waiting for $Uri"
}

function Get-ShortcutPath {
    $startMenu = [Environment]::GetFolderPath('StartMenu')
    return Join-Path (Join-Path (Join-Path $startMenu 'Programs') 'Scoop Apps') "$shortcutName.lnk"
}

function Get-AppRoot {
    $root = Join-Path (Join-Path $env:SCOOP 'apps') "$appName\current"
    if (!(Test-Path -LiteralPath $root)) {
        throw "Scoop did not create the current directory: $root"
    }
    return (Resolve-Path -LiteralPath $root).Path
}

function Wait-Path {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [int]$TimeoutSeconds = 60
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if (Test-Path -LiteralPath $Path) {
            return
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Timed out waiting for path: $Path"
}

function Stop-OwnProcesses {
    param([switch]$KeepServices)
    if (!$KeepServices -and $gatewayProcess -and !$gatewayProcess.HasExited) {
        Stop-Process -Id $gatewayProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if (!$KeepServices -and $httpProcess -and !$httpProcess.HasExited) {
        Stop-Process -Id $httpProcess.Id -Force -ErrorAction SilentlyContinue
    }

    # Start-Process on a .lnk does not return the Electron child. Restrict the
    # cleanup to processes whose executable is inside this run's Scoop tree.
    if ($env:SCOOP) {
        $appsRoot = Join-Path $env:SCOOP 'apps'
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($appsRoot, [StringComparison]::OrdinalIgnoreCase) } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    }
}

function Start-AppFromShortcut {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string]$Shortcut
    )

    $savedPath = $env:PATH
    try {
        # The app must not discover the Python/Node/Git toolchain used by the
        # acceptance job as a fallback local Hermes runtime.
        $env:PATH = "$Root;$env:SystemRoot\System32;$env:SystemRoot"
        Start-Process -FilePath $Shortcut | Out-Null
    } finally {
        $env:PATH = $savedPath
    }
}

function Get-AppTreeFingerprint {
    param([Parameter(Mandatory = $true)][string]$Root)

    $rows = @(
        Get-ChildItem -LiteralPath $Root -File -Recurse -Force |
            Sort-Object FullName |
            ForEach-Object {
                $relative = [IO.Path]::GetRelativePath($Root, $_.FullName)
                "{0}|{1}|{2}" -f $relative, $_.Length, $_.LastWriteTimeUtc.Ticks
            }
    )
    return ($rows -join "`n")
}

function Find-Dumpbin {
    $command = Get-Command dumpbin.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (Test-Path -LiteralPath $vswhere) {
        $installPath = (& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath).Trim()
        if ($installPath) {
            $candidate = Get-ChildItem -LiteralPath (Join-Path $installPath 'VC\Tools\MSVC') -Filter dumpbin.exe -File -Recurse -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -match '\\bin\\Hostx64\\x64\\dumpbin\.exe$' } |
                Sort-Object FullName |
                Select-Object -Last 1
            if ($candidate) {
                return $candidate.FullName
            }
        }
    }

    $roots = @(
        (Join-Path ${env:ProgramFiles} 'Microsoft Visual Studio'),
        (Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio')
    ) | Where-Object { Test-Path -LiteralPath $_ }
    $fallback = Get-ChildItem -LiteralPath $roots -Filter dumpbin.exe -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\bin\\Hostx64\\x64\\dumpbin\.exe$' } |
        Sort-Object FullName |
        Select-Object -Last 1
    if ($fallback) {
        return $fallback.FullName
    }
    return $null
}

function Get-PEImportEvidence {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string]$ExecutableName
    )

    $dumpbin = Find-Dumpbin
    if (!$dumpbin) {
        throw 'dumpbin.exe was not available on the Windows runner; PE runtime evidence cannot be collected'
    }

    $files = @()
    $exe = Join-Path $Root $ExecutableName
    if (Test-Path -LiteralPath $exe) {
        $files += Get-Item -LiteralPath $exe
    }
    $files += @(Get-ChildItem -LiteralPath $Root -File -Recurse -Filter '*.node' -ErrorAction SilentlyContinue)
    if ($files.Count -eq 0) {
        throw 'No executable or native .node files were found in the installed package'
    }

    $records = @()
    $allImports = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($file in $files | Sort-Object FullName -Unique) {
        $dump = (& $dumpbin /DEPENDENTS $file.FullName 2>&1 | Out-String)
        $imports = @(
            [regex]::Matches($dump, '(?im)^\s+([A-Za-z0-9_.-]+\.dll)\s*$') |
                ForEach-Object { $_.Value.Trim() } |
                Sort-Object -Unique
        )
        foreach ($import in $imports) {
            [void]$allImports.Add($import)
        }
        $records += [ordered]@{
            file = [IO.Path]::GetRelativePath($Root, $file.FullName)
            imports = @($imports)
        }
    }

    $shipped = @(Get-ChildItem -LiteralPath $Root -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^(api-ms-win-crt-|ucrtbase|vcruntime|msvcp|concrt|msvcr).*\.dll$' } |
        ForEach-Object { [IO.Path]::GetRelativePath($Root, $_.FullName) } |
        Sort-Object)
    $runtimeImports = @($allImports | Where-Object { $_ -match '^(api-ms-win-crt-|ucrtbase|vcruntime|msvcp|concrt|msvcr)' } | Sort-Object)

    return [ordered]@{
        tool = $dumpbin
        files = @($records)
        runtimeImports = @($runtimeImports)
        shippedRuntimeDlls = @($shipped)
        runnerIsClean = $false
        runnerLimit = 'GitHub-hosted Windows includes system runtimes and is not a clean Windows installation.'
        conclusion = if ($shipped.Count -gt 0) {
            'The package ships at least one CRT/runtime DLL; launch success still does not prove independence from the runner image.'
        } elseif ($runtimeImports.Count -gt 0) {
            'Native imports reference Windows CRT/runtime components not shipped in this package; a clean Windows host needs the corresponding supported VC++ runtime/system components.'
        } else {
            'No CRT/runtime imports were observed in the inspected executable/native modules; launch success was still observed only on the non-clean runner.'
        }
    }
}

function New-EphemeralSecret {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [Convert]::ToBase64String($bytes)
}

$httpErrorLog = Join-Path $scratch 'artifact-http-error.log'

try {
    $zip = Get-ChildItem -LiteralPath $ArtifactDirectory -Filter '*.zip' -File | Select-Object -First 1
    if (!$zip) {
        throw "No ZIP artifact found in $ArtifactDirectory"
    }
    $zipPath = $zip.FullName
    $receiptPath = Join-Path $ArtifactDirectory 'provenance.json'
    if (!(Test-Path -LiteralPath $receiptPath)) {
        throw 'provenance.json is missing from the build artifact'
    }
    $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
    $zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($receipt.sha256 -and $receipt.sha256.ToLowerInvariant() -ne $zipHash) {
        throw "Artifact SHA256 does not match provenance.json"
    }
    $sourceCommit = (& git -C $UpstreamDirectory rev-parse HEAD).Trim()
    if ($receipt.commit -and $receipt.commit -ne $sourceCommit) {
        throw "Artifact provenance commit $($receipt.commit) does not match checkout $sourceCommit"
    }
    $executableName = [string]$receipt.executable
    if (!$executableName) {
        throw 'provenance.json does not name the executable'
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        $payloadEntries = @($archive.Entries | Where-Object { $_.FullName -replace '\\', '/' -match '^resources/agent-payload(?:/|$)' })
        if ($payloadEntries.Count -gt 0) {
            throw 'Light artifact contains resources/agent-payload'
        }
    } finally {
        $archive.Dispose()
    }

    $secret = New-EphemeralSecret
    Write-Output "::add-mask::$secret"
    $wrongSecret = "$secret-wrong"
    $env:HERMES_DASHBOARD_SESSION_TOKEN = $secret
    $env:HERMES_DESKTOP = '1'
    foreach ($name in @('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'XAI_API_KEY', 'GEMINI_API_KEY', 'HF_TOKEN', 'HUGGINGFACE_TOKEN')) {
        Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force -Path $gatewayHome, $hermesHome, $userData | Out-Null

    $python = (Get-Command python -ErrorAction Stop).Source
    $gatewayPort = Get-Random -Minimum 22000 -Maximum 32000
    $artifactPort = Get-Random -Minimum 32000 -Maximum 42000
    $gatewayUri = "http://127.0.0.1:$gatewayPort"
    $env:HERMES_HOME = $gatewayHome
    $gatewayProcess = Start-Process -FilePath $python -ArgumentList @('-m', 'hermes_cli.main', 'serve', '--host', '127.0.0.1', "--port=$gatewayPort", '--skip-build') -WorkingDirectory $UpstreamDirectory -RedirectStandardOutput $gatewayLog -RedirectStandardError $gatewayErrorLog -PassThru -WindowStyle Hidden
    Wait-Http -Uri "$gatewayUri/api/status" -TimeoutSeconds 120 | Out-Null
    $env:HERMES_HOME = $hermesHome
    $env:HERMES_DESKTOP_USER_DATA_DIR = $userData

    $httpProcess = Start-Process -FilePath $python -ArgumentList @('-m', 'http.server', $artifactPort, '--bind', '127.0.0.1', '--directory', $ArtifactDirectory) -RedirectStandardOutput $httpLog -RedirectStandardError $httpErrorLog -PassThru -WindowStyle Hidden
    $artifactUri = "http://127.0.0.1:$artifactPort/$([Uri]::EscapeDataString($zip.Name))"
    Wait-Http -Uri $artifactUri -TimeoutSeconds 30 | Out-Null

    $env:SCOOP = Join-Path $scratch 'scoop'
    New-Item -ItemType Directory -Force -Path $env:SCOOP | Out-Null
    if (!(Get-Command scoop -ErrorAction SilentlyContinue)) {
        Invoke-Expression (Invoke-RestMethod -Uri 'https://get.scoop.sh')
    }
    $env:PATH = "$(Join-Path $env:SCOOP 'shims');$env:PATH"
    if (!(Get-Command scoop -ErrorAction SilentlyContinue)) {
        throw 'Scoop was not available after bootstrap'
    }

    $runtimeVersion = "0.0.0-test-before-$($sourceCommit.Substring(0, 7))"
    $runtimeAfterVersion = "0.0.1-test-after-$($sourceCommit.Substring(0, 7))"
    $cdpPort = Get-Random -Minimum 43000 -Maximum 50000
    $cdpArgument = "--remote-debugging-port=$cdpPort"
    $manifest = [ordered]@{
        version = $runtimeVersion
        description = 'TEST-ONLY Hermes Light acceptance manifest; never a production Scoop manifest.'
        homepage = 'https://github.com/NousResearch/hermes-agent'
        license = 'UNOFFICIAL-TEST-BUILD'
        url = $artifactUri
        hash = $zipHash
        shortcuts = @(, @($executableName, $shortcutName, $cdpArgument))
    }
    Write-EvidenceJson -Path $manifestPath -Value $manifest
    Invoke-Scoop -Arguments @('install', $manifestPath)
    $installedRoot = Get-AppRoot
    $shortcutPath = Get-ShortcutPath
    Wait-Path -Path $shortcutPath
    $shortcutShell = New-Object -ComObject WScript.Shell
    $shortcutTarget = $shortcutShell.CreateShortcut([string]$shortcutPath)
    $shortcutTargetPath = [string]$shortcutTarget.TargetPath
    $shortcutTargetArguments = [string]$shortcutTarget.Arguments
    if ([IO.Path]::GetFullPath($shortcutTargetPath) -ne [IO.Path]::GetFullPath((Join-Path $installedRoot $executableName))) {
        throw "Scoop shortcut target does not point at the installed executable"
    }
    if ($shortcutTargetArguments -notmatch [regex]::Escape($cdpArgument)) {
        throw 'Scoop start-menu shortcut did not preserve the CDP launch argument'
    }

    $runtimeEvidence = Get-PEImportEvidence -Root $installedRoot -ExecutableName $executableName
    Write-EvidenceJson -Path (Join-Path $OutputDirectory 'runtime-evidence.json') -Value $runtimeEvidence

    $node = (Get-Command node -ErrorAction Stop).Source
    $acceptanceJs = Join-Path $PSScriptRoot 'accept-hermes-light.cjs'
    $beforeJson = Join-Path $OutputDirectory 'before.json'
    $isPreview = ($PackageVersion -eq 'preview') -or ([string]$receipt.preview -ieq 'true')
    $previewSwitch = if ($isPreview) { '--preview' } else { $null }
    Start-AppFromShortcut -Root $installedRoot -Shortcut $shortcutPath
    Start-Sleep -Seconds 2
    & $node $acceptanceJs --phase before --cdp-port $cdpPort --app-root $installedRoot --gateway-url $gatewayUri --secret $secret --wrong-secret $wrongSecret --result $beforeJson $previewSwitch
    if ($LASTEXITCODE -ne 0) {
        throw "Electron acceptance (before update) failed with exit code $LASTEXITCODE"
    }

    # Ensure the Electron process is gone before Scoop replaces the current tree.
    Stop-OwnProcesses -KeepServices
    Start-Sleep -Seconds 2
    $manifest.version = $runtimeAfterVersion
    Write-EvidenceJson -Path $manifestPath -Value $manifest
    Invoke-Scoop -Arguments @('update', $appName)
    $installedRoot = Get-AppRoot
    $shortcutPath = Get-ShortcutPath
    Wait-Path -Path $shortcutPath
    $afterJson = Join-Path $OutputDirectory 'after.json'
    Start-AppFromShortcut -Root $installedRoot -Shortcut $shortcutPath
    Start-Sleep -Seconds 2
    & $node $acceptanceJs --phase after --cdp-port $cdpPort --app-root $installedRoot --gateway-url $gatewayUri --secret $secret --wrong-secret $wrongSecret --result $afterJson $previewSwitch
    if ($LASTEXITCODE -ne 0) {
        throw "Electron acceptance (after update) failed with exit code $LASTEXITCODE"
    }
    Stop-OwnProcesses

    $userDataMarker = Join-Path $userData 'acceptance-user-data-marker.txt'
    Set-Content -LiteralPath $userDataMarker -Value 'safe-test-data' -Encoding utf8NoBOM
    Invoke-Scoop -Arguments @('uninstall', $appName)
    if (Test-Path -LiteralPath (Join-Path (Join-Path $env:SCOOP 'apps') $appName)) {
        throw 'Scoop app directory remains after uninstall'
    }
    if (Test-Path -LiteralPath $shortcutPath) {
        throw 'Scoop start-menu shortcut remains after uninstall'
    }
    if (!(Test-Path -LiteralPath $userData) -or !(Test-Path -LiteralPath $userDataMarker)) {
        throw 'Expected user data did not remain after Scoop uninstall'
    }

    $summary = [ordered]@{
        schema = 1
        status = 'passed'
        upstream = 'NousResearch/hermes-agent'
        sourceRef = $SourceRef
        commit = $sourceCommit
        bucketPackageVersion = $PackageVersion
        artifact = $zip.Name
        artifactSha256 = $zipHash
        preview = $receipt.preview -eq $true
        testManifest = [IO.Path]::GetFileName($manifestPath)
        testOnlyManifest = $true
        scoop = [ordered]@{
            app = $appName
            beforeVersion = $runtimeVersion
            afterVersion = $runtimeAfterVersion
            shortcut = "$shortcutName.lnk"
            startMenu = [Environment]::GetFolderPath('StartMenu')
            installedAndUpdated = $true
            uninstalledAppAndShortcut = $true
            userDataRemained = $true
        }
        gateway = [ordered]@{
            command = 'hermes serve --host 127.0.0.1 --port <ephemeral> --skip-build'
            sourceCommit = $sourceCommit
            url = $gatewayUri
            auth = 'HERMES_DASHBOARD_SESSION_TOKEN; ephemeral random value generated and masked in the job'
            providerCredentials = 'none; provider credential environment variables removed'
            runner = 'same Windows runner, localhost, read-only acceptance job'
        }
        runtime = $runtimeEvidence
        localExecution = 'Light ZIP has no resources/agent-payload; probe observed bootstrap-needed and no local agent was started. The first-run local-install affordance is bootstrap-only, not a bundled local backend.'
        updater = if ($receipt.preview -eq $true) {
            'Scoop-installed preview returned external/unsupported, reason=commit-build, and refused apply; app tree fingerprint was unchanged.'
        } else {
            'Scoop-installed stable package returned external/manual-only (reason=bundled-not-appinstaller) and refused in-place apply; app tree fingerprint was unchanged.'
        }
        retention = 'Settings and tokenSet survived the test-only Scoop update; the post-update app revalidated the same gateway.'
        uninstall = 'App directory and Start-menu shortcut removed; HERMES_HOME/user data remained by design.'
    }
    Write-EvidenceJson -Path (Join-Path $OutputDirectory 'acceptance.json') -Value $summary
    $exitCode = 0
} catch {
    $failure = Redact $_.Exception.Message
    $exitCode = 1
    Write-Error $failure
} finally {
    Stop-OwnProcesses
    if ($secret) {
        foreach ($path in @($gatewayLog, $gatewayErrorLog, $httpLog, $httpErrorLog)) {
            if (Test-Path -LiteralPath $path) {
                $safeName = Split-Path -Leaf $path
                $contents = Get-Content -LiteralPath $path -Raw -ErrorAction SilentlyContinue
                if ($null -eq $contents) {
                    $contents = ''
                }
                $contents.Replace($secret, '[REDACTED]') |
                    Set-Content -LiteralPath (Join-Path $OutputDirectory $safeName) -Encoding utf8NoBOM
            }
        }
    }
    if ($failure -and !(Test-Path -LiteralPath (Join-Path $OutputDirectory 'acceptance.json'))) {
        Write-EvidenceJson -Path (Join-Path $OutputDirectory 'acceptance.json') -Value ([ordered]@{
            schema = 1
            status = 'failed'
            error = $failure
            upstream = 'NousResearch/hermes-agent'
            sourceRef = $SourceRef
            commit = if ($sourceCommit) { $sourceCommit } else { $null }
            artifact = if ($zipPath) { [IO.Path]::GetFileName($zipPath) } else { $null }
        })
    }
}

if ($exitCode -ne 0) {
    exit $exitCode
}
