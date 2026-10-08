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
. (Join-Path $PSScriptRoot 'accept-hermes-light-helpers.ps1')

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
$runtimeFailure = $null
$exitCode = 0
$secret = $null
$appName = 'hermes-agent-light-acceptance'
$shortcutName = 'Hermes Light Acceptance'
$bucketName = 'hermes-light-acceptance'
$bucketDirectory = Join-Path $scratch 'acceptance-bucket'
$bucketManifestPath = Join-Path (Join-Path $bucketDirectory 'bucket') "$appName.json"
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


function Get-SystemDllNames {
    $names = @{}
    foreach ($directory in @(
        (Join-Path $env:SystemRoot 'System32'),
        (Join-Path $env:SystemRoot 'SysWOW64')
    ) | Where-Object { Test-Path -LiteralPath $_ }) {
        Get-ChildItem -LiteralPath $directory -File -Filter '*.dll' -ErrorAction SilentlyContinue |
            ForEach-Object { $names[$_.Name] = $true }
    }
    foreach ($registryPath in @(
        'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\KnownDLLs',
        'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\KnownDLLs32'
    )) {
        if (Test-Path -LiteralPath $registryPath) {
            $properties = Get-ItemProperty -LiteralPath $registryPath
            foreach ($property in $properties.PSObject.Properties) {
                if ($property.Name -notmatch '^PS' -and $property.Value) {
                    $names[[string]$property.Value] = $true
                }
            }
        }
    }
    return $names
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

    $files = @(Get-ChildItem -LiteralPath $Root -File -Recurse -Force -ErrorAction Stop |
        Where-Object { $_.Extension -in @('.dll', '.exe', '.node') } |
        Sort-Object FullName -Unique)
    if ($files.Count -eq 0) {
        throw 'No executable, DLL, or native .node files were found in the installed package'
    }
    $expectedExecutable = Join-Path $Root $ExecutableName
    if (!(Test-Path -LiteralPath $expectedExecutable)) {
        throw "The manifest executable is missing from the installed package: $ExecutableName"
    }

    $shippedByName = @{}
    foreach ($file in $files) {
        if (!$shippedByName.ContainsKey($file.Name)) {
            $shippedByName[$file.Name] = @()
        }
        $shippedByName[$file.Name] += $file
    }
    $systemNames = Get-SystemDllNames
    $records = @()
    $allImports = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $unparseable = @()
    $unresolved = @()
    $missingRuntime = @()
    $crtPattern = '^(api-ms-win-crt-|ucrtbase|vcruntime|msvcp|concrt|msvcr).*\.dll$'

    foreach ($file in $files) {
        $relativeFile = [IO.Path]::GetRelativePath($Root, $file.FullName)
        $dump = (& $dumpbin /DEPENDENTS $file.FullName 2>&1 | Out-String)
        $dumpExitCode = $LASTEXITCODE
        if ($dumpExitCode -ne 0 -or $dump -notmatch '(?im)^\s*Image has the following dependencies:\s*$') {
            $unparseable += $relativeFile
            $records += [ordered]@{
                file = $relativeFile
                imports = @()
                resolutions = @()
                parseError = "dumpbin /DEPENDENTS exit=$dumpExitCode"
            }
            continue
        }
        $imports = @(
            [regex]::Matches($dump, '(?im)^\s+([A-Za-z0-9_.-]+\.dll)\s*$') |
                ForEach-Object { $_.Groups[1].Value } |
                Sort-Object -Unique
        )
        $resolutions = @()
        foreach ($import in $imports) {
            [void]$allImports.Add($import)
            $resolution = $null
            $localCandidate = Join-Path $file.DirectoryName $import
            if (Test-Path -LiteralPath $localCandidate -PathType Leaf) {
                $resolution = [ordered]@{
                    name = $import
                    kind = 'app-local'
                    path = [IO.Path]::GetRelativePath($Root, (Resolve-Path -LiteralPath $localCandidate).Path)
                }
            } elseif ($shippedByName.ContainsKey($import)) {
                $resolution = [ordered]@{
                    name = $import
                    kind = 'app-tree'
                    path = [IO.Path]::GetRelativePath($Root, $shippedByName[$import][0].FullName)
                }
            } elseif ($systemNames.ContainsKey($import)) {
                $resolution = [ordered]@{
                    name = $import
                    kind = 'system-known-dll'
                    path = $import
                }
            } elseif ($import -match '^(?:api|ext)-ms-win-') {
                $resolution = [ordered]@{
                    name = $import
                    kind = 'system-api-set'
                    path = 'Windows API Set'
                }
            } elseif (Test-Path -LiteralPath (Join-Path $env:SystemRoot "System32\$import") -PathType Leaf) {
                $resolution = [ordered]@{
                    name = $import
                    kind = 'system32'
                    path = (Join-Path $env:SystemRoot "System32\$import")
                }
            }
            if (!$resolution) {
                $unresolved += "$relativeFile -> $import"
            } elseif ($import -match $crtPattern -and $resolution.kind -notin @('app-local', 'app-tree')) {
                $missingRuntime += "$relativeFile -> $import ($($resolution.kind))"
            }
            if ($resolution) {
                $resolutions += $resolution
            }
        }
        $records += [ordered]@{
            file = $relativeFile
            imports = @($imports)
            resolutions = @($resolutions)
        }
    }

    $runtimeImports = @($allImports | Where-Object { $_ -match $crtPattern } | Sort-Object)
    $shippedRuntimeDlls = @($files |
        Where-Object { $_.Extension -eq '.dll' -and $_.Name -match $crtPattern } |
        ForEach-Object { [IO.Path]::GetRelativePath($Root, $_.FullName) } |
        Sort-Object)
    $accepted = $unparseable.Count -eq 0 -and $unresolved.Count -eq 0 -and $missingRuntime.Count -eq 0
    $failures = @()
    if ($unparseable.Count -gt 0) {
        $failures += "unparseable PE files: $($unparseable -join ', ')"
    }
    if ($unresolved.Count -gt 0) {
        $failures += "unresolved imports: $($unresolved -join ', ')"
    }
    if ($missingRuntime.Count -gt 0) {
        $failures += "VC++/UCRT imports are not shipped by the artifact: $($missingRuntime -join ', ')"
    }

    return [ordered]@{
        tool = $dumpbin
        files = @($records)
        fileCount = $files.Count
        runtimeImports = @($runtimeImports)
        shippedRuntimeDlls = @($shippedRuntimeDlls)
        unparseable = @($unparseable)
        unresolved = @($unresolved)
        missingShippedRuntime = @($missingRuntime)
        accepted = $accepted
        runnerIsClean = $false
        runnerLimit = 'GitHub-hosted Windows includes system runtimes and is not a clean Windows installation.'
        conclusion = if ($accepted) {
            'Every bundled PE import parsed and resolved to the app tree or Windows KnownDLLs/System32/API Set; no unshipped VC++/UCRT import was observed.'
        } else {
            $failures -join '; '
        }
        failures = @($failures)
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
    $bucketDirectory = Join-Path (Join-Path $env:SCOOP 'buckets') $bucketName
    $bucketManifestPath = Join-Path (Join-Path $bucketDirectory 'bucket') "$appName.json"
    New-Item -ItemType Directory -Force -Path (Join-Path $bucketDirectory 'bucket') | Out-Null
    Write-EvidenceJson -Path $bucketManifestPath -Value $manifest
    Write-EvidenceJson -Path $manifestPath -Value $manifest
    Invoke-Scoop -Arguments @('install', $appName)
    $installedRoot = Get-AppRoot
    $beforeInstall = Get-ScoopInstalledState -AppName $appName -BucketManifestPath $bucketManifestPath
    $shortcutPath = Get-ShortcutPath
    Wait-Path -Path $shortcutPath
    $beforeShortcut = Get-ShortcutState -Path $shortcutPath
    $expectedBeforeShortcut = [IO.Path]::GetFullPath((Join-Path $beforeInstall.currentTargetResolved $executableName))
    if ($beforeShortcut.resolvedTarget -ne $expectedBeforeShortcut) {
        throw "Scoop start-menu shortcut resolved target $($beforeShortcut.resolvedTarget) does not match installed executable $expectedBeforeShortcut"
    }
    if ($beforeInstall.version -ne $runtimeVersion) {
        throw "Scoop installed unexpected initial version: $($beforeInstall.version)"
    }

    $runtimeEvidence = Get-PEImportEvidence -Root $installedRoot -ExecutableName $executableName
    Write-EvidenceJson -Path (Join-Path $OutputDirectory 'runtime-evidence.json') -Value $runtimeEvidence
    if (!$runtimeEvidence.accepted) {
        $runtimeFailure = "Bundled PE runtime acceptance failed: $($runtimeEvidence.conclusion)"
    }

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
    Write-EvidenceJson -Path $bucketManifestPath -Value $manifest
    Write-EvidenceJson -Path $manifestPath -Value $manifest
    Invoke-Scoop -Arguments @('update', $appName)
    $installedRoot = Get-AppRoot
    $afterInstall = Get-ScoopInstalledState -AppName $appName -BucketManifestPath $bucketManifestPath
    $shortcutPath = Get-ShortcutPath
    Wait-Path -Path $shortcutPath
    $afterShortcut = Get-ShortcutState -Path $shortcutPath
    $expectedAfterShortcut = [IO.Path]::GetFullPath((Join-Path $afterInstall.currentTargetResolved $executableName))
    try {
        $updateAssertion = Assert-ScoopUpdateSwitch `
            -BeforeInstall $beforeInstall `
            -AfterInstall $afterInstall `
            -BeforeShortcut $beforeShortcut `
            -AfterShortcut $afterShortcut `
            -ExpectedVersion $runtimeAfterVersion `
            -ExpectedCurrentTarget $afterInstall.currentTargetResolved `
            -ExpectedShortcutTarget $expectedAfterShortcut
        $updateAssertionStatus = 'passed'
    } catch {
        $updateAssertion = [ordered]@{
            status = 'failed'
            error = $_.Exception.Message
            noOpRejected = $false
        }
        $updateAssertionStatus = 'failed'
        Write-EvidenceJson -Path (Join-Path $OutputDirectory 'scoop-update-evidence.json') -Value ([ordered]@{
            before = $beforeInstall
            after = $afterInstall
            beforeShortcut = $beforeShortcut
            afterShortcut = $afterShortcut
            assertion = $updateAssertion
        })
        throw
    }
    Write-EvidenceJson -Path (Join-Path $OutputDirectory 'scoop-update-evidence.json') -Value ([ordered]@{
        before = $beforeInstall
        after = $afterInstall
        beforeShortcut = $beforeShortcut
        afterShortcut = $afterShortcut
        assertion = $updateAssertion
        assertionStatus = $updateAssertionStatus
    })

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
    if ($runtimeFailure) {
        throw $runtimeFailure
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
            beforeVersion = $updateEvidence.beforeVersion
            afterVersion = $updateEvidence.afterVersion
            beforeCurrentTarget = $updateEvidence.beforeCurrentTarget
            afterCurrentTarget = $updateEvidence.afterCurrentTarget
            beforeShortcutTarget = $updateEvidence.beforeShortcutTarget
            afterShortcutTarget = $updateEvidence.afterShortcutTarget
            expectedVersion = $updateEvidence.expectedVersion
            updateAssertion = 'installed manifest/install versions changed to expected test-only version; resolved current target changed; shortcut target read back'
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
        updater = 'Scoop update used a disposable local bucket with distinct test-only manifests; installed manifest/install versions, resolved current target, and shortcut target were read back and asserted.'
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
