function Get-ScoopInstalledState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$AppName,
        [Parameter(Mandatory = $false)]
        [string]$BucketManifestPath
    )

    if (!$env:SCOOP) {
        throw 'SCOOP is not set while reading installed state'
    }
    $appDirectory = Join-Path (Join-Path $env:SCOOP 'apps') $AppName
    $currentLink = Join-Path $appDirectory 'current'
    if (!(Test-Path -LiteralPath $currentLink)) {
        throw "Scoop current link is missing: $currentLink"
    }

    $currentItem = Get-Item -LiteralPath $currentLink -Force
    $rawTarget = [string]$currentItem.Target
    if ($rawTarget) {
        if ([IO.Path]::IsPathRooted($rawTarget)) {
            $resolvedCurrent = [IO.Path]::GetFullPath($rawTarget)
        } else {
            $resolvedCurrent = [IO.Path]::GetFullPath((Join-Path $appDirectory $rawTarget))
        }
    } else {
        $resolvedCurrent = (Resolve-Path -LiteralPath $currentLink).Path
    }
    $manifestPath = Join-Path $resolvedCurrent 'manifest.json'
    $manifestSource = 'installed-current'
    if (!(Test-Path -LiteralPath $manifestPath)) {
        if (!$BucketManifestPath -or !(Test-Path -LiteralPath $BucketManifestPath)) {
            throw "Installed manifest is missing and no bucket manifest was supplied: $manifestPath"
        }
        $manifestPath = (Resolve-Path -LiteralPath $BucketManifestPath).Path
        $manifestSource = 'disposable-bucket'
    }

    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $manifestVersion = [string]$manifest.version
    $installPath = Join-Path $appDirectory 'install.json'
    if (!(Test-Path -LiteralPath $installPath)) {
        $installPath = Join-Path $resolvedCurrent 'install.json'
    }
    $installSource = 'install-receipt'
    $listOutput = ''
    if (Test-Path -LiteralPath $installPath) {
        $install = Get-Content -LiteralPath $installPath -Raw | ConvertFrom-Json
        $installVersion = [string]$install.version
    } else {
        $installPath = $null
        $installSource = 'scoop-list'
        $listOutput = (& scoop list $AppName 2>&1 | Out-String)
        $cleanList = [regex]::Replace($listOutput, "`e\[[0-9;]*m", '')
        $listPattern = "(?im)^\s*$([regex]::Escape($AppName))\s+(\S+)\s+"
        $listMatch = [regex]::Match($cleanList, $listPattern)
        if (!$listMatch.Success) {
            throw "Scoop install receipt is missing and scoop list did not report $AppName"
        }
        $installVersion = $listMatch.Groups[1].Value
    }
    if (!$manifestVersion -or !$installVersion) {
        throw "Installed Scoop state has no manifest/list version: $resolvedCurrent"
    }
    if ($manifestVersion -ne $installVersion) {
        throw "Installed manifest/list versions disagree: $manifestVersion vs $installVersion"
    }

    return [ordered]@{
        version = $manifestVersion
        manifestVersion = $manifestVersion
        installVersion = $installVersion
        currentLink = $currentLink
        currentTargetRaw = $rawTarget
        currentTargetResolved = $resolvedCurrent
        manifestPath = $manifestPath
        manifestSource = $manifestSource
        installSource = $installSource
        scoopList = $listOutput
        installPath = $installPath
    }
}

function Get-ShortcutState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (!(Test-Path -LiteralPath $Path)) {
        throw "Shortcut is missing: $Path"
    }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $targetPath = [string]$shortcut.TargetPath
    $arguments = [string]$shortcut.Arguments
    if (!$targetPath) {
        throw "Shortcut has no target: $Path"
    }
    return [ordered]@{
        path = $Path
        target = [IO.Path]::GetFullPath($targetPath)
        arguments = $arguments
    }
}

function Assert-ScoopUpdateSwitch {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.IDictionary]$BeforeInstall,
        [Parameter(Mandatory = $true)]
        [System.Collections.IDictionary]$AfterInstall,
        [Parameter(Mandatory = $true)]
        [System.Collections.IDictionary]$BeforeShortcut,
        [Parameter(Mandatory = $true)]
        [System.Collections.IDictionary]$AfterShortcut,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedVersion,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedCurrentTarget,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedShortcutTarget
    )

    $errors = @()
    if (!$BeforeInstall.version -or !$AfterInstall.version) {
        $errors += 'before/after installed version is missing'
    } elseif ($BeforeInstall.version -eq $AfterInstall.version) {
        $errors += "Scoop update was a no-op: before and after version are $($AfterInstall.version)"
    }
    if ($AfterInstall.version -ne $ExpectedVersion) {
        $errors += "after installed version $($AfterInstall.version) does not equal expected $ExpectedVersion"
    }
    if (!$BeforeInstall.currentTargetResolved -or !$AfterInstall.currentTargetResolved) {
        $errors += 'before/after resolved current target is missing'
    } elseif ($BeforeInstall.currentTargetResolved -eq $AfterInstall.currentTargetResolved) {
        $errors += 'Scoop current target did not change across update'
    }
    if ($AfterInstall.currentTargetResolved -ne $ExpectedCurrentTarget) {
        $errors += "after resolved current target $($AfterInstall.currentTargetResolved) does not equal expected $ExpectedCurrentTarget"
    }
    if (!$BeforeShortcut.target -or !$AfterShortcut.target) {
        $errors += 'before/after shortcut target is missing'
    }
    if ($AfterShortcut.target -ne $ExpectedShortcutTarget) {
        $errors += "after shortcut target $($AfterShortcut.target) does not equal expected $ExpectedShortcutTarget"
    }
    if ($errors.Count -gt 0) {
        throw "Scoop update switch assertion failed:`n- $($errors -join "`n- ")"
    }

    return [ordered]@{
        beforeVersion = $BeforeInstall.version
        afterVersion = $AfterInstall.version
        beforeCurrentTarget = $BeforeInstall.currentTargetResolved
        afterCurrentTarget = $AfterInstall.currentTargetResolved
        beforeShortcutTarget = $BeforeShortcut.target
        afterShortcutTarget = $AfterShortcut.target
        expectedVersion = $ExpectedVersion
        expectedCurrentTarget = $ExpectedCurrentTarget
        expectedShortcutTarget = $ExpectedShortcutTarget
        noOpRejected = $true
    }
}
