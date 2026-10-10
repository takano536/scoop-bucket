BeforeAll {
    . (Join-Path $PSScriptRoot '../scripts/accept-hermes-desktop-light-helpers.ps1')
    function New-TestScoopUpdateFixtures {
        $beforeInstall = [ordered]@{
            version = '0.0.0-test-before'
            currentTargetResolved = 'C:\scoop\apps\hermes-desktop-light-acceptance\0.0.0-test-before'
        }
        $afterInstall = [ordered]@{
            version = '0.0.1-test-after'
            currentTargetResolved = 'C:\scoop\apps\hermes-desktop-light-acceptance\0.0.1-test-after'
        }
        $beforeShortcut = [ordered]@{
            target = 'C:\scoop\apps\hermes-desktop-light-acceptance\current\Hermes Light.exe'
            resolvedTarget = 'C:\scoop\apps\hermes-desktop-light-acceptance\0.0.0-test-before\Hermes Light.exe'
        }
        $afterShortcut = [ordered]@{
            target = $beforeShortcut.target
            resolvedTarget = 'C:\scoop\apps\hermes-desktop-light-acceptance\0.0.1-test-after\Hermes Light.exe'
        }
        $assertion = Assert-ScoopUpdateSwitch -BeforeInstall $beforeInstall -AfterInstall $afterInstall `
            -BeforeShortcut $beforeShortcut -AfterShortcut $afterShortcut `
            -ExpectedVersion $afterInstall.version `
            -ExpectedCurrentTarget $afterInstall.currentTargetResolved `
            -ExpectedShortcutTarget $afterShortcut.resolvedTarget

        return [ordered]@{
            BeforeInstall = $beforeInstall
            AfterInstall = $afterInstall
            BeforeShortcut = $beforeShortcut
            AfterShortcut = $afterShortcut
            Assertion = $assertion
        }
    }
}


Describe 'Hermes Desktop Light updater channel expectations' {
    It 'maps a development receipt to commit-build even when preview is false' {
        $receipt = [pscustomobject]@{
            channel = 'development'
            development = $true
            preview = $false
        }

        Get-HermesAcceptanceDevelopmentMode -Receipt $receipt -PackageVersion '0.0.0-alpha.dev.1-r1' | Should -BeTrue
    }
    It 'maps an official canary Desktop release to external non-preview acceptance' {
        $receipt = [pscustomobject]@{
            channel = 'desktop-release'
            development = $true
            upstreamChannel = 'canary'
            preview = $false
        }

        Get-HermesAcceptanceDevelopmentMode -Receipt $receipt -PackageVersion '26.1009.7.410-alpha.dev.1-r1' | Should -BeFalse
    }


    It 'maps a stable receipt to bundled-not-appinstaller' {
        $receipt = [pscustomobject]@{
            channel = 'stable'
            development = $false
            preview = $false
        }

        Get-HermesAcceptanceDevelopmentMode -Receipt $receipt -PackageVersion '0.22.0-r1' | Should -BeFalse
    }

    It 'rejects a channel and development flag mismatch' {
        $receipt = [pscustomobject]@{
            channel = 'development'
            development = $false
            preview = $false
        }

        {
            Get-HermesAcceptanceDevelopmentMode -Receipt $receipt -PackageVersion '0.0.0-alpha.dev.1-r1'
        } | Should -Throw '*development=true*'
    }
}


Describe 'Hermes Desktop Light Scoop update assertions' {
    BeforeEach {
        $fixtures = New-TestScoopUpdateFixtures
    }
    It 'rejects a no-op update with unchanged current target' {
        $beforeInstall = [ordered]@{
            version = '0.0.0-test-before'
            currentTargetResolved = 'C:\scoop\apps\hermes-desktop-light-acceptance\0.0.0-test-before'
        }
        $afterInstall = [ordered]@{
            version = '0.0.0-test-before'
            currentTargetResolved = 'C:\scoop\apps\hermes-desktop-light-acceptance\0.0.0-test-before'
        }
        $beforeShortcut = [ordered]@{
            target = 'C:\scoop\apps\hermes-desktop-light-acceptance\current\Hermes Light.exe'
            resolvedTarget = 'C:\scoop\apps\hermes-desktop-light-acceptance\0.0.0-test-before\Hermes Light.exe'
        }
        $afterShortcut = [ordered]@{
            target = $beforeShortcut.target
            resolvedTarget = $beforeShortcut.resolvedTarget
        }

        {
            Assert-ScoopUpdateSwitch -BeforeInstall $beforeInstall -AfterInstall $afterInstall `
                -BeforeShortcut $beforeShortcut -AfterShortcut $afterShortcut `
                -ExpectedVersion '0.0.1-test-after' `
                -ExpectedCurrentTarget 'C:\scoop\apps\hermes-desktop-light-acceptance\0.0.1-test-after' `
                -ExpectedShortcutTarget 'C:\scoop\apps\hermes-desktop-light-acceptance\0.0.1-test-after\Hermes Light.exe'
        } | Should -Throw '*no-op*'
    }

    It 'accepts distinct installed versions and changed current target' {
        $beforeInstall = [ordered]@{
            version = '0.0.0-test-before'
            currentTargetResolved = 'C:\scoop\apps\hermes-desktop-light-acceptance\0.0.0-test-before'
        }
        $afterInstall = [ordered]@{
            version = '0.0.1-test-after'
            currentTargetResolved = 'C:\scoop\apps\hermes-desktop-light-acceptance\0.0.1-test-after'
        }
        $beforeShortcut = [ordered]@{
            target = 'C:\scoop\apps\hermes-desktop-light-acceptance\current\Hermes Light.exe'
            resolvedTarget = 'C:\scoop\apps\hermes-desktop-light-acceptance\0.0.0-test-before\Hermes Light.exe'
        }
        $afterShortcut = [ordered]@{
            target = $beforeShortcut.target
            resolvedTarget = 'C:\scoop\apps\hermes-desktop-light-acceptance\0.0.1-test-after\Hermes Light.exe'
        }

        $result = Assert-ScoopUpdateSwitch -BeforeInstall $beforeInstall -AfterInstall $afterInstall `
            -BeforeShortcut $beforeShortcut -AfterShortcut $afterShortcut `
            -ExpectedVersion '0.0.1-test-after' `
            -ExpectedCurrentTarget 'C:\scoop\apps\hermes-desktop-light-acceptance\0.0.1-test-after' `
            -ExpectedShortcutTarget 'C:\scoop\apps\hermes-desktop-light-acceptance\0.0.1-test-after\Hermes Light.exe'

        $result.noOpRejected | Should -BeTrue
        $result.beforeVersion | Should -Not -Be $result.afterVersion
        $result.afterVersion | Should -Be '0.0.1-test-after'
        $result.afterCurrentTarget | Should -Be $afterInstall.currentTargetResolved
    }

    It 'returns observed and expected values for a valid update summary' {
        $summary = New-ScoopUpdateSummary -Assertion $fixtures.Assertion `
            -BeforeInstall $fixtures.BeforeInstall -AfterInstall $fixtures.AfterInstall `
            -BeforeShortcut $fixtures.BeforeShortcut -AfterShortcut $fixtures.AfterShortcut

        $summary.afterVersion | Should -Be $fixtures.AfterInstall.version
        $summary.afterVersion | Should -Be $fixtures.Assertion.expectedVersion
        $summary.afterCurrentTarget | Should -Be $fixtures.AfterInstall.currentTargetResolved
        $summary.afterCurrentTarget | Should -Be $fixtures.Assertion.expectedCurrentTarget
        $summary.afterShortcutResolvedTarget | Should -Be $fixtures.AfterShortcut.resolvedTarget
        $summary.afterShortcutResolvedTarget | Should -Be $fixtures.Assertion.expectedShortcutTarget
        $summary.updateAssertion | Should -Be 'passed'
    }

    It 'rejects a missing or failed update assertion' {
        {
            New-ScoopUpdateSummary -Assertion $null `
                -BeforeInstall $fixtures.BeforeInstall -AfterInstall $fixtures.AfterInstall `
                -BeforeShortcut $fixtures.BeforeShortcut -AfterShortcut $fixtures.AfterShortcut
        } | Should -Throw '*requires a passed update assertion*'

        $failedAssertion = [ordered]@{ noOpRejected = $false }
        {
            New-ScoopUpdateSummary -Assertion $failedAssertion `
                -BeforeInstall $fixtures.BeforeInstall -AfterInstall $fixtures.AfterInstall `
                -BeforeShortcut $fixtures.BeforeShortcut -AfterShortcut $fixtures.AfterShortcut
        } | Should -Throw '*requires a passed update assertion*'
    }

    It 'rejects an empty observed install version' {
        $afterInstall = [ordered]@{
            version = ''
            currentTargetResolved = $fixtures.AfterInstall.currentTargetResolved
        }

        {
            New-ScoopUpdateSummary -Assertion $fixtures.Assertion `
                -BeforeInstall $fixtures.BeforeInstall -AfterInstall $afterInstall `
                -BeforeShortcut $fixtures.BeforeShortcut -AfterShortcut $fixtures.AfterShortcut
        } | Should -Throw '*evidence is missing*'
    }

    It 'rejects a missing observed shortcut target' {
        $afterShortcut = [ordered]@{
            target = ''
            resolvedTarget = $fixtures.AfterShortcut.resolvedTarget
        }

        {
            New-ScoopUpdateSummary -Assertion $fixtures.Assertion `
                -BeforeInstall $fixtures.BeforeInstall -AfterInstall $fixtures.AfterInstall `
                -BeforeShortcut $fixtures.BeforeShortcut -AfterShortcut $afterShortcut
        } | Should -Throw '*evidence is missing*'
    }

    It 'rejects an assertion value that differs from observed evidence' {
        $assertion = [ordered]@{
            beforeVersion = $fixtures.BeforeInstall.version
            afterVersion = $fixtures.AfterInstall.version
            beforeCurrentTarget = $fixtures.BeforeInstall.currentTargetResolved
            afterCurrentTarget = 'C:\scoop\apps\hermes-desktop-light-acceptance\unexpected'
            beforeShortcutTarget = $fixtures.BeforeShortcut.target
            afterShortcutTarget = $fixtures.AfterShortcut.target
            beforeShortcutResolvedTarget = $fixtures.BeforeShortcut.resolvedTarget
            afterShortcutResolvedTarget = $fixtures.AfterShortcut.resolvedTarget
            expectedVersion = $fixtures.AfterInstall.version
            expectedCurrentTarget = $fixtures.AfterInstall.currentTargetResolved
            expectedShortcutTarget = $fixtures.AfterShortcut.resolvedTarget
            noOpRejected = $true
        }

        {
            New-ScoopUpdateSummary -Assertion $assertion `
                -BeforeInstall $fixtures.BeforeInstall -AfterInstall $fixtures.AfterInstall `
                -BeforeShortcut $fixtures.BeforeShortcut -AfterShortcut $fixtures.AfterShortcut
        } | Should -Throw '*does not match observed*'
    }

    It 'rejects a no-op version and target update' {
        $beforeInstall = [ordered]@{
            version = '0.0.1-test-same'
            currentTargetResolved = 'C:\scoop\apps\hermes-desktop-light-acceptance\0.0.1-test-same'
        }
        $afterInstall = [ordered]@{
            version = '0.0.1-test-same'
            currentTargetResolved = 'C:\scoop\apps\hermes-desktop-light-acceptance\0.0.1-test-same'
        }
        $beforeShortcut = [ordered]@{
            target = 'C:\scoop\apps\hermes-desktop-light-acceptance\current\Hermes Light.exe'
            resolvedTarget = 'C:\scoop\apps\hermes-desktop-light-acceptance\0.0.1-test-same\Hermes Light.exe'
        }
        $afterShortcut = [ordered]@{
            target = $beforeShortcut.target
            resolvedTarget = $beforeShortcut.resolvedTarget
        }
        $assertion = [ordered]@{
            beforeVersion = $beforeInstall.version
            afterVersion = $afterInstall.version
            beforeCurrentTarget = $beforeInstall.currentTargetResolved
            afterCurrentTarget = $afterInstall.currentTargetResolved
            beforeShortcutTarget = $beforeShortcut.target
            afterShortcutTarget = $afterShortcut.target
            beforeShortcutResolvedTarget = $beforeShortcut.resolvedTarget
            afterShortcutResolvedTarget = $afterShortcut.resolvedTarget
            expectedVersion = $afterInstall.version
            expectedCurrentTarget = $afterInstall.currentTargetResolved
            expectedShortcutTarget = $afterShortcut.resolvedTarget
            noOpRejected = $true
        }

        {
            New-ScoopUpdateSummary -Assertion $assertion `
                -BeforeInstall $beforeInstall -AfterInstall $afterInstall `
                -BeforeShortcut $beforeShortcut -AfterShortcut $afterShortcut
        } | Should -Throw '*no-op*'
    }

    It 'rejects an after version that does not equal the expected version' {
        $assertion = [ordered]@{
            beforeVersion = $fixtures.BeforeInstall.version
            afterVersion = $fixtures.AfterInstall.version
            beforeCurrentTarget = $fixtures.BeforeInstall.currentTargetResolved
            afterCurrentTarget = $fixtures.AfterInstall.currentTargetResolved
            beforeShortcutTarget = $fixtures.BeforeShortcut.target
            afterShortcutTarget = $fixtures.AfterShortcut.target
            beforeShortcutResolvedTarget = $fixtures.BeforeShortcut.resolvedTarget
            afterShortcutResolvedTarget = $fixtures.AfterShortcut.resolvedTarget
            expectedVersion = '0.0.9-test-unexpected'
            expectedCurrentTarget = $fixtures.AfterInstall.currentTargetResolved
            expectedShortcutTarget = $fixtures.AfterShortcut.resolvedTarget
            noOpRejected = $true
        }

        {
            New-ScoopUpdateSummary -Assertion $assertion `
                -BeforeInstall $fixtures.BeforeInstall -AfterInstall $fixtures.AfterInstall `
                -BeforeShortcut $fixtures.BeforeShortcut -AfterShortcut $fixtures.AfterShortcut
        } | Should -Throw '*does not equal expected*'
    }

    It 'rejects an after shortcut target that does not equal the expected target' {
        $assertion = [ordered]@{
            beforeVersion = $fixtures.BeforeInstall.version
            afterVersion = $fixtures.AfterInstall.version
            beforeCurrentTarget = $fixtures.BeforeInstall.currentTargetResolved
            afterCurrentTarget = $fixtures.AfterInstall.currentTargetResolved
            beforeShortcutTarget = $fixtures.BeforeShortcut.target
            afterShortcutTarget = $fixtures.AfterShortcut.target
            beforeShortcutResolvedTarget = $fixtures.BeforeShortcut.resolvedTarget
            afterShortcutResolvedTarget = $fixtures.AfterShortcut.resolvedTarget
            expectedVersion = $fixtures.AfterInstall.version
            expectedCurrentTarget = $fixtures.AfterInstall.currentTargetResolved
            expectedShortcutTarget = 'C:\scoop\apps\hermes-desktop-light-acceptance\0.0.1-test-after\Unexpected.exe'
            noOpRejected = $true
        }

        {
            New-ScoopUpdateSummary -Assertion $assertion `
                -BeforeInstall $fixtures.BeforeInstall -AfterInstall $fixtures.AfterInstall `
                -BeforeShortcut $fixtures.BeforeShortcut -AfterShortcut $fixtures.AfterShortcut
        } | Should -Throw '*does not equal expected*'
    }
}

Describe 'Hermes Desktop Light Windows runtime classification' {
    It 'accepts a host-resolved Windows 10 API set as OS-provided' {
        $result = Get-WindowsImportClassification -ImportName 'api-ms-win-crt-runtime-l1-1-0.dll' `
            -ResolutionKind 'system-api-set' -ApiSetResolved $true

        $result.kind | Should -Be 'system-api-set'
        $result.osProvided | Should -BeTrue
        $result.accepted | Should -BeTrue
    }

    It 'rejects an unshipped VC++ redistributable import' {
        $result = Get-WindowsImportClassification -ImportName 'vcruntime140.dll' `
            -ResolutionKind 'system32'

        $result.kind | Should -Be 'missing-redistributable'
        $result.redistributable | Should -BeTrue
        $result.accepted | Should -BeFalse
    }

    It 'accepts a VC++ redistributable shipped next to its importer' {
        $result = Get-WindowsImportClassification -ImportName 'vcruntime140.dll' `
            -ResolutionKind 'app-local'

        $result.kind | Should -Be 'app-local'
        $result.accepted | Should -BeTrue
    }

    It 'rejects an unresolvable unknown DLL' {
        $result = Get-WindowsImportClassification -ImportName 'unknown-runtime.dll' `
            -ResolutionKind 'unresolved'

        $result.kind | Should -Be 'unresolved'
        $result.accepted | Should -BeFalse
    }
}
