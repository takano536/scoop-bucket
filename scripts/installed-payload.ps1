#Requires -Version 5.1
<#
.SYNOPSIS
    Checks that an installed app contains the files its manifest declares.
.DESCRIPTION
    `scoop install` exits successfully even when the downloaded archive no longer
    has the layout the manifest expects. A shortcut whose target is missing only
    prints "Creating shortcut ... failed", and an archive that extracts nothing
    still counts as installed, so neither fails the install.

    This helper reports those problems so the install verification can fail.
    Installer manifests (`installer`) are skipped because they place their files
    outside the Scoop app directory on purpose.
#>
function Test-InstalledPayload {
    [CmdletBinding()]
    [OutputType([string[]])]
    param(
        [Parameter(Mandatory = $true)][string]$Prefix,
        [Parameter(Mandatory = $true)][psobject]$Manifest,
        [string]$Architecture = ''
    )

    $problems = New-Object 'System.Collections.Generic.List[string]'

    if ($Manifest.installer) {
        return $problems.ToArray()
    }

    if (-not (Test-Path -LiteralPath $Prefix -PathType Container)) {
        $problems.Add("installed app directory was not found: $Prefix")
        return $problems.ToArray()
    }

    $metadata = @('scoop-manifest.json', 'manifest.json', 'install.json')
    $entries = @(Get-ChildItem -LiteralPath $Prefix -Force | Where-Object { $metadata -notcontains $_.Name })
    if ($entries.Count -eq 0) {
        $problems.Add('installed app directory contains no files besides Scoop metadata')
    }

    $target = $Manifest
    if ($Architecture -and $Manifest.architecture) {
        $property = $Manifest.architecture.PSObject.Properties[$Architecture]
        if ($null -ne $property) { $target = $property.Value }
    }

    foreach ($shortcut in @($target.shortcuts)) {
        if ($null -eq $shortcut) { continue }
        if ($shortcut -isnot [array]) {
            $problems.Add("shortcut entry is not an array: $shortcut")
            continue
        }
        $file = [IO.Path]::Combine($Prefix, [string]$shortcut[0])
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            $problems.Add("shortcut target was not installed: $($shortcut[0])")
        }
        if ($shortcut.Count -ge 4 -and $shortcut[3]) {
            $icon = [IO.Path]::Combine($Prefix, [string]$shortcut[3])
            if (-not (Test-Path -LiteralPath $icon -PathType Leaf)) {
                $problems.Add("shortcut icon was not installed: $($shortcut[3])")
            }
        }
    }

    foreach ($bin in @($target.bin)) {
        if ($null -eq $bin) { continue }
        $name = if ($bin -is [array]) { [string]$bin[0] } else { [string]$bin }
        $file = [IO.Path]::Combine($Prefix, $name)
        if (-not (Test-Path -LiteralPath $file -PathType Leaf) -and -not (Get-Command $name -ErrorAction SilentlyContinue)) {
            $problems.Add("bin target was not installed: $name")
        }
    }

    return $problems.ToArray()
}
