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
. (Join-Path $PSScriptRoot 'accept-hermes-desktop-light-helpers.ps1')

$ArtifactDirectory = (Resolve-Path -LiteralPath $ArtifactDirectory).Path
$UpstreamDirectory = (Resolve-Path -LiteralPath $UpstreamDirectory).Path
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

$scratch = Join-Path $env:RUNNER_TEMP ("hermes-desktop-light-acceptance-{0}" -f ([guid]::NewGuid().ToString('N')))
New-Item -ItemType Directory -Force -Path $scratch | Out-Null
$manifestPath = Join-Path $scratch 'hermes-desktop-light-acceptance.json'
$httpLog = Join-Path $scratch 'artifact-http.log'
$gatewayLog = Join-Path $scratch 'gateway.log'
$gatewayErrorLog = Join-Path $scratch 'gateway-error.log'
$httpProcess = $null
$gatewayProcess = $null
$failure = $null
$runtimeFailure = $null
$exitCode = 0
$secret = $null
$appName = 'hermes-desktop-light-acceptance'
$shortcutName = 'Hermes Desktop Light Acceptance'
$bucketName = 'hermes-desktop-light-acceptance'
$bucketDirectory = Join-Path $scratch 'acceptance-bucket'
$bucketManifestPath = Join-Path (Join-Path $bucketDirectory 'bucket') "$appName.json"
$zipPath = $null
$installedRoot = $null
$hermesHome = Join-Path $scratch 'hermes-home'
$userData = Join-Path $scratch 'desktop-user-data'
$gatewayHome = Join-Path $scratch 'gateway-home'
$stageLog = Join-Path $OutputDirectory 'stages.log'
$acceptanceProcess = $null
$electronProcessIds = [Collections.Generic.HashSet[int]]::new()
$cdpPort = $null
$nodeTimeoutSeconds = 180

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
function Write-Stage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [AllowNull()]
        [string]$Details = ''
    )

    $suffix = if ($Details) { " $(Redact $Details)" } else { '' }
    $line = "[acceptance] $([DateTime]::UtcNow.ToString('o')) stage=$Name$suffix"
    $line | Tee-Object -FilePath $stageLog -Append
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

function Stop-ProcessTree {
    param([int]$ProcessId)

    if ($ProcessId -le 0) {
        return
    }
    try {
        & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
    } catch {
        # The process may have exited between discovery and taskkill.
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Get-AppProcessIds {
    param([Parameter(Mandatory = $true)][string]$Root)

    $roots = @(
        $Root,
        (Split-Path -Parent $Root)
    ) | Where-Object { $_ } |
        ForEach-Object { ([IO.Path]::GetFullPath($_)).TrimEnd('\') + '\' }
    @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $process = $_
            $process.ExecutablePath -and
            @($roots | Where-Object {
                $_.Length -gt 0 -and $process.ExecutablePath.StartsWith($_, [StringComparison]::OrdinalIgnoreCase)
            }).Count -gt 0
        } |
        ForEach-Object { [int]$_.ProcessId })
}

function Stop-OwnProcesses {
    param([switch]$KeepServices)

    if ($acceptanceProcess -and !$acceptanceProcess.HasExited) {
        Stop-ProcessTree -ProcessId $acceptanceProcess.Id
    }
    if (!$KeepServices -and $gatewayProcess -and !$gatewayProcess.HasExited) {
        Stop-ProcessTree -ProcessId $gatewayProcess.Id
    }
    if (!$KeepServices -and $httpProcess -and !$httpProcess.HasExited) {
        Stop-ProcessTree -ProcessId $httpProcess.Id
    }

    # Start-Process on a .lnk does not return the Electron child. Restrict the
    # cleanup to processes whose executable is inside this run's installed app.
    if ($installedRoot -and (Test-Path -LiteralPath $installedRoot)) {
        foreach ($processId in @(Get-AppProcessIds -Root $installedRoot)) {
            [void]$electronProcessIds.Add($processId)
        }
    }
    foreach ($processId in @($electronProcessIds)) {
        Stop-ProcessTree -ProcessId $processId
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
function Write-RedactedArtifact {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,
        [Parameter(Mandatory = $true)]
        [string]$DestinationPath
    )

    if (!(Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        return
    }
    try {
        $contents = Get-Content -LiteralPath $SourcePath -Raw -ErrorAction Stop
        if ($null -eq $contents) {
            $contents = ''
        }
        if ($contents.Length -gt 2000000) {
            $contents = $contents.Substring(0, 2000000) + "`n[truncated]"
        }
        (Redact $contents) | Set-Content -LiteralPath $DestinationPath -Encoding utf8NoBOM
    } catch {
        "Unable to collect $([IO.Path]::GetFileName($SourcePath)): $(Redact $_.Exception.Message)" |
            Set-Content -LiteralPath $DestinationPath -Encoding utf8NoBOM
    }
}

function Write-Diagnostics {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Reason
    )

    $diagnosticsDirectory = Join-Path $OutputDirectory 'diagnostics'
    New-Item -ItemType Directory -Force -Path $diagnosticsDirectory | Out-Null
    Write-EvidenceJson -Path (Join-Path $diagnosticsDirectory 'diagnostics.json') -Value ([ordered]@{
        schema = 1
        status = 'failed'
        reason = Redact $Reason
        cdpPort = $cdpPort
        appRoot = $installedRoot
        timestamp = [DateTime]::UtcNow.ToString('o')
    })

    try {
        $processRows = @(
            Get-CimInstance Win32_Process -ErrorAction Stop |
                Sort-Object ProcessId |
                ForEach-Object {
                    [ordered]@{
                        processId = [int]$_.ProcessId
                        parentProcessId = [int]$_.ParentProcessId
                        name = [string]$_.Name
                        executablePath = [string]$_.ExecutablePath
                        commandLine = Redact $_.CommandLine
                    }
                }
        )
        Write-EvidenceJson -Path (Join-Path $diagnosticsDirectory 'processes.json') -Value $processRows
    } catch {
        "Unable to collect process list: $(Redact $_.Exception.Message)" |
            Set-Content -LiteralPath (Join-Path $diagnosticsDirectory 'processes.error.txt') -Encoding utf8NoBOM
    }

    if ($cdpPort) {
        try {
            $targetResponse = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$cdpPort/json/list" -TimeoutSec 5
            (Redact $targetResponse.Content) |
                Set-Content -LiteralPath (Join-Path $diagnosticsDirectory 'cdp-targets.json') -Encoding utf8NoBOM
        } catch {
            "Unable to collect CDP targets: $(Redact $_.Exception.Message)" |
                Set-Content -LiteralPath (Join-Path $diagnosticsDirectory 'cdp-targets.error.txt') -Encoding utf8NoBOM
        }
    }

    foreach ($logPath in @($gatewayLog, $gatewayErrorLog, $httpLog, $httpErrorLog)) {
        if ($logPath) {
            $destination = Join-Path $diagnosticsDirectory ([IO.Path]::GetFileName($logPath))
            Write-RedactedArtifact -SourcePath $logPath -DestinationPath $destination
        }
    }
    foreach ($streamLog in @(
        (Join-Path $OutputDirectory 'electron-before.stdout.log'),
        (Join-Path $OutputDirectory 'electron-before.stderr.log'),
        (Join-Path $OutputDirectory 'electron-after.stdout.log'),
        (Join-Path $OutputDirectory 'electron-after.stderr.log')
    )) {
        Write-RedactedArtifact -SourcePath $streamLog -DestinationPath (Join-Path $diagnosticsDirectory ([IO.Path]::GetFileName($streamLog)))
    }
    if (Test-Path -LiteralPath $userData) {
        Get-ChildItem -LiteralPath $userData -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -in @('.log', '.txt') } |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 20 |
            ForEach-Object {
                $safeName = "user-data-$([Math]::Abs($_.FullName.GetHashCode()))-$($_.Name)"
                Write-RedactedArtifact -SourcePath $_.FullName -DestinationPath (Join-Path $diagnosticsDirectory $safeName)
            }
    }
}

function Invoke-NodeAcceptance {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Phase,
        [Parameter(Mandatory = $true)]
        [string]$Node,
        [Parameter(Mandatory = $true)]
        [string]$AcceptanceJs,
        [Parameter(Mandatory = $true)]
        [string]$ResultPath,
        [AllowNull()]
        [string]$PreviewSwitch
    )

    $stdoutPath = Join-Path $OutputDirectory "electron-$Phase.stdout.log"
    $stderrPath = Join-Path $OutputDirectory "electron-$Phase.stderr.log"
    $arguments = @(
        $AcceptanceJs,
        '--phase', $Phase,
        '--cdp-port', [string]$cdpPort,
        '--app-root', $installedRoot,
        '--gateway-url', $gatewayUri,
        '--secret', $secret,
        '--wrong-secret', $wrongSecret,
        '--result', $ResultPath,
        '--diagnostics-directory', $OutputDirectory,
        '--stage-log', $stageLog
    )
    if ($PreviewSwitch) {
        $arguments += $PreviewSwitch
    }

    Write-Stage "electron-$Phase-start" "timeoutSeconds=$nodeTimeoutSeconds"
    $script:acceptanceProcess = Start-Process `
        -FilePath $Node `
        -ArgumentList $arguments `
        -WorkingDirectory $PSScriptRoot `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru `
        -WindowStyle Hidden
    try {
        $deadline = [DateTime]::UtcNow.AddSeconds($nodeTimeoutSeconds)
        while (!$script:acceptanceProcess.HasExited -and [DateTime]::UtcNow -lt $deadline) {
            Start-Sleep -Milliseconds 250
        }
        if (!$script:acceptanceProcess.HasExited) {
            Write-Stage "electron-$Phase-timeout" "timeoutSeconds=$nodeTimeoutSeconds"
            Write-Diagnostics -Reason "Timed out waiting for Electron acceptance ($Phase) after $nodeTimeoutSeconds seconds"
            Stop-ProcessTree -ProcessId $script:acceptanceProcess.Id
            throw "Timed out waiting for Electron acceptance ($Phase) after $nodeTimeoutSeconds seconds"
        }
        $nodeExitCode = $script:acceptanceProcess.ExitCode
        Write-Stage "electron-$Phase-exit" "exitCode=$nodeExitCode"
        if ($nodeExitCode -ne 0) {
            $errorTail = ''
            if (Test-Path -LiteralPath $stderrPath) {
                $errorTail = (Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue)
            }
            throw "Electron acceptance ($Phase) failed with exit code ${nodeExitCode}: $(Redact $errorTail)"
        }
    } finally {
        $script:acceptanceProcess = $null
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

function Test-WindowsApiSetResolution {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if ($null -eq ('HermesDesktopLightNativeMethodsV2' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class HermesDesktopLightNativeMethodsV2
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr LoadLibraryEx(string lpFileName, IntPtr hFile, uint dwFlags);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool FreeLibrary(IntPtr hModule);

    public static bool Probe(string name, uint flags)
    {
        var handle = LoadLibraryEx(name, IntPtr.Zero, flags);
        if (handle == IntPtr.Zero)
            return false;
        FreeLibrary(handle);
        return true;
    }
}
'@
    }

    if ([HermesDesktopLightNativeMethodsV2]::Probe($Name, 0x00000002)) {
        return [ordered]@{
            name = $Name
            resolved = $true
            mechanism = 'LoadLibraryEx(LOAD_LIBRARY_AS_DATAFILE)'
            error = 0
            minimumWindows = 'Windows 10'
        }
    }
    if ([HermesDesktopLightNativeMethodsV2]::Probe($Name, 0)) {
        return [ordered]@{
            name = $Name
            resolved = $true
            mechanism = 'LoadLibraryEx'
            error = 0
            minimumWindows = 'Windows 10'
        }
    }
    return [ordered]@{
        name = $Name
        resolved = $false
        mechanism = 'LoadLibraryEx(LOAD_LIBRARY_AS_DATAFILE) and LoadLibraryEx'
        minimumWindows = 'Windows 10'
    }
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
    $apiSetProbeCache = @{}
    $apiSetProbes = @()
    $runtimePattern = '^(?:(?:api|ext)-ms-win-.+|ucrtbase|vcruntime140(?:_\d+)?|msvcp140(?:_\d+)?|concrt140|vccorlib140|mfc\d+[ud]?|msvcr\d+)\.dll$'

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
            $apiSetProbe = $null
            if ($import -match '^(?:api|ext)-ms-win-') {
                if ($null -eq $apiSetProbeCache[$import]) {
                    $apiSetProbeCache[$import] = Test-WindowsApiSetResolution -Name $import
                    $apiSetProbes += $apiSetProbeCache[$import]
                }
                $apiSetProbe = $apiSetProbeCache[$import]
            }
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
            } elseif ($apiSetProbe -and $apiSetProbe.resolved) {
                $resolution = [ordered]@{
                    name = $import
                    kind = 'system-api-set'
                    path = 'Windows 10+ ApiSet schema'
                    apiSetProbe = $apiSetProbe
                }
            } elseif (Test-Path -LiteralPath (Join-Path $env:SystemRoot "System32\$import") -PathType Leaf) {
                $resolution = [ordered]@{
                    name = $import
                    kind = 'system32'
                    path = (Join-Path $env:SystemRoot "System32\$import")
                }
            }
            $resolutionKind = if ($resolution) { $resolution.kind } else { 'unresolved' }
            $classification = Get-WindowsImportClassification `
                -ImportName $import `
                -ResolutionKind $resolutionKind `
                -ApiSetResolved ($apiSetProbe -and $apiSetProbe.resolved)
            if (!$resolution -or !$classification.accepted) {
                if (!$resolution -or $classification.kind -eq 'unresolved-api-set') {
                    $unresolved += "$relativeFile -> $import ($($classification.reason))"
                } else {
                    $missingRuntime += "$relativeFile -> $import ($($classification.reason))"
                }
            }
            if ($resolution) {
                $resolution.classification = $classification.kind
                $resolutions += $resolution
            }
        }
        $records += [ordered]@{
            file = $relativeFile
            imports = @($imports)
            resolutions = @($resolutions)
        }
    }

    $runtimeImports = @($allImports | Where-Object { $_ -match $runtimePattern } | Sort-Object)
    $osProvidedImports = @($allImports |
        Where-Object { $_ -match '^(?:api|ext)-ms-win-.+\.dll$' -or $_ -ieq 'ucrtbase.dll' } |
        Sort-Object)
    $redistributableImports = @($allImports |
        Where-Object { $_ -match '^(?:vcruntime140(?:_\d+)?|msvcp140(?:_\d+)?|concrt140|vccorlib140|mfc\d+[ud]?|msvcr\d+)\.dll$' } |
        Sort-Object)
    $shippedRuntimeDlls = @($files |
        Where-Object { $_.Extension -eq '.dll' -and $_.Name -match '^(?:vcruntime140(?:_\d+)?|msvcp140(?:_\d+)?|concrt140|vccorlib140|mfc\d+[ud]?|msvcr\d+)\.dll$' } |
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
        $failures += "VC++ redistributable imports are not shipped by the artifact: $($missingRuntime -join ', ')"
    }

    return [ordered]@{
        tool = $dumpbin
        files = @($records)
        fileCount = $files.Count
        runtimeImports = @($runtimeImports)
        osProvidedImports = @($osProvidedImports)
        redistributableImports = @($redistributableImports)
        apiSetProbes = @($apiSetProbes)
        shippedRuntimeDlls = @($shippedRuntimeDlls)
        unparseable = @($unparseable)
        unresolved = @($unresolved)
        missingShippedRuntime = @($missingRuntime)
        accepted = $accepted
        runnerIsClean = $false
        runnerLimit = 'GitHub-hosted Windows includes system runtimes and is not a clean Windows installation.'
        minimumWindows = 'Windows 10+ (Electron supported minimum)'
        conclusion = if ($accepted) {
            'Every bundled PE import parsed and resolved to the app tree or Windows 10+ KnownDLLs/System32/ApiSet schema; no unshipped VC++ redistributable import was observed.'
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
    Write-Stage 'acceptance-start'
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
    # The upstream desktop shows an active-work quit dialog unless automated
    # teardown opts out; CDP has nobody that can answer that modal.
    $env:HERMES_DESKTOP_SKIP_QUIT_CONFIRM = '1'
    foreach ($name in @('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'XAI_API_KEY', 'GEMINI_API_KEY', 'HF_TOKEN', 'HUGGINGFACE_TOKEN')) {
        Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force -Path $gatewayHome, $hermesHome, $userData | Out-Null

    $python = (Get-Command python -ErrorAction Stop).Source
    $gatewayPort = Get-Random -Minimum 22000 -Maximum 32000
    $artifactPort = Get-Random -Minimum 32000 -Maximum 42000
    $gatewayUri = "http://127.0.0.1:$gatewayPort"
    Write-Stage 'gateway-start' "port=$gatewayPort"
    $env:HERMES_HOME = $gatewayHome
    $gatewayProcess = Start-Process -FilePath $python -ArgumentList @('-m', 'hermes_cli.main', 'serve', '--host', '127.0.0.1', "--port=$gatewayPort", '--skip-build') -WorkingDirectory $UpstreamDirectory -RedirectStandardOutput $gatewayLog -RedirectStandardError $gatewayErrorLog -PassThru -WindowStyle Hidden
    Wait-Http -Uri "$gatewayUri/api/status" -TimeoutSeconds 120 | Out-Null
    Write-Stage 'gateway-ready'
    $env:HERMES_HOME = $hermesHome
    $env:HERMES_DESKTOP_USER_DATA_DIR = $userData

    $httpProcess = Start-Process -FilePath $python -ArgumentList @('-m', 'http.server', $artifactPort, '--bind', '127.0.0.1', '--directory', $ArtifactDirectory) -RedirectStandardOutput $httpLog -RedirectStandardError $httpErrorLog -PassThru -WindowStyle Hidden
    $artifactUri = "http://127.0.0.1:$artifactPort/$([Uri]::EscapeDataString($zip.Name))"
    Wait-Http -Uri $artifactUri -TimeoutSeconds 30 | Out-Null
    Write-Stage 'artifact-http-ready' "port=$artifactPort"

    $env:SCOOP = Join-Path $scratch 'scoop'
    New-Item -ItemType Directory -Force -Path $env:SCOOP | Out-Null
    if (!(Get-Command scoop -ErrorAction SilentlyContinue)) {
        Invoke-Expression (Invoke-RestMethod -Uri 'https://get.scoop.sh')
    }
    $env:PATH = "$(Join-Path $env:SCOOP 'shims');$env:PATH"
    if (!(Get-Command scoop -ErrorAction SilentlyContinue)) {
        throw 'Scoop was not available after bootstrap'
    }
    Write-Stage 'scoop-ready'

    $runtimeVersion = '0.0.0-alpha.dev.1-r1'
    $runtimeAfterVersion = $PackageVersion
    $cdpPort = Get-Random -Minimum 43000 -Maximum 50000
    $cdpArgument = "--remote-debugging-port=$cdpPort"
    $manifest = [ordered]@{
        version = $runtimeVersion
        description = 'TEST-ONLY Hermes Desktop Light acceptance manifest; never a production Scoop manifest.'
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
    Write-Stage 'scoop-install-start' "version=$runtimeVersion"
    Invoke-Scoop -Arguments @('install', $appName)
    Write-Stage 'scoop-install-complete'
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
    Write-Stage 'scoop-install-state-verified'
    Write-Stage 'runtime-evidence-start'

    $runtimeEvidence = Get-PEImportEvidence -Root $installedRoot -ExecutableName $executableName
    Write-EvidenceJson -Path (Join-Path $OutputDirectory 'runtime-evidence.json') -Value $runtimeEvidence
    Write-Stage 'runtime-evidence-written'
    if (!$runtimeEvidence.accepted) {
        $runtimeFailure = "Bundled PE runtime acceptance failed: $($runtimeEvidence.conclusion)"
    }

    $node = (Get-Command node -ErrorAction Stop).Source
    $acceptanceJs = Join-Path $PSScriptRoot 'accept-hermes-desktop-light.cjs'
    $beforeJson = Join-Path $OutputDirectory 'before.json'
    $isDevelopment = Get-HermesAcceptanceDevelopmentMode -Receipt $receipt -PackageVersion $PackageVersion
    $previewSwitch = if ($isDevelopment) { '--preview' } else { $null }
    Write-Stage 'electron-launch-before'
    Start-AppFromShortcut -Root $installedRoot -Shortcut $shortcutPath
    Start-Sleep -Seconds 2
    Invoke-NodeAcceptance -Phase 'before' -Node $node -AcceptanceJs $acceptanceJs -ResultPath $beforeJson -PreviewSwitch $previewSwitch

    # Ensure the Electron process is gone before Scoop replaces the current tree.
    Stop-OwnProcesses -KeepServices
    Start-Sleep -Seconds 2
    $manifest.version = $runtimeAfterVersion
    Write-EvidenceJson -Path $bucketManifestPath -Value $manifest
    Write-EvidenceJson -Path $manifestPath -Value $manifest
    Write-Stage 'scoop-update-start' "version=$runtimeAfterVersion"
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
    $updateSummary = New-ScoopUpdateSummary -Assertion $updateAssertion `
        -BeforeInstall $beforeInstall -AfterInstall $afterInstall `
        -BeforeShortcut $beforeShortcut -AfterShortcut $afterShortcut
    Write-EvidenceJson -Path (Join-Path $OutputDirectory 'scoop-update-evidence.json') -Value ([ordered]@{
        before = $beforeInstall
        after = $afterInstall
        beforeShortcut = $beforeShortcut
        afterShortcut = $afterShortcut
        assertion = $updateAssertion
        assertionStatus = $updateAssertionStatus
        summary = $updateSummary
    })
    Write-Stage 'scoop-update-evidence-written'

    $afterJson = Join-Path $OutputDirectory 'after.json'
    Write-Stage 'electron-launch-after'
    Start-AppFromShortcut -Root $installedRoot -Shortcut $shortcutPath
    Start-Sleep -Seconds 2
    Invoke-NodeAcceptance -Phase 'after' -Node $node -AcceptanceJs $acceptanceJs -ResultPath $afterJson -PreviewSwitch $previewSwitch
    Stop-OwnProcesses

    $userDataMarker = Join-Path $userData 'acceptance-user-data-marker.txt'
    Set-Content -LiteralPath $userDataMarker -Value 'safe-test-data' -Encoding utf8NoBOM
    Write-Stage 'scoop-uninstall-start'
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
    Write-Stage 'scoop-uninstall-complete'
    if ($runtimeFailure) {
        throw $runtimeFailure
    }

    $scoopSummary = [ordered]@{ app = $appName }
    foreach ($key in $updateSummary.Keys) {
        $scoopSummary[$key] = $updateSummary[$key]
    }
    $scoopSummary.shortcut = "$shortcutName.lnk"
    $scoopSummary.startMenu = [Environment]::GetFolderPath('StartMenu')
    $scoopSummary.installedAndUpdated = $true
    $scoopSummary.uninstalledAppAndShortcut = $true
    $scoopSummary.userDataRemained = $true
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
        scoop = $scoopSummary
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
        updater = "Scoop update migrated the historical $runtimeVersion manifest to the new Desktop-release $runtimeAfterVersion version using a disposable local bucket; installed manifest/install versions, resolved current target, and shortcut target were read back and asserted."
        uninstall = 'App directory and Start-menu shortcut removed; HERMES_HOME/user data remained by design.'
    }
    Write-EvidenceJson -Path (Join-Path $OutputDirectory 'acceptance.json') -Value $summary
    $exitCode = 0
} catch {
    $failure = Redact $_.Exception.Message
    $exitCode = 1
    Write-Stage 'failure' $failure
    try {
        Write-Diagnostics -Reason $failure
    } catch {
        Write-Error (Redact "Failed to write acceptance diagnostics: $($_.Exception.Message)")
    }
    Write-Error $failure
} finally {
    try {
        Stop-OwnProcesses
    } catch {
        Write-Error (Redact "Process cleanup failed: $($_.Exception.Message)")
    }
    Write-Stage 'cleanup-complete'
    foreach ($path in @($gatewayLog, $gatewayErrorLog, $httpLog, $httpErrorLog)) {
        if ($path) {
            $safeName = Split-Path -Leaf $path
            Write-RedactedArtifact -SourcePath $path -DestinationPath (Join-Path $OutputDirectory $safeName)
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
