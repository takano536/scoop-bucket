BeforeAll {
    . (Join-Path $PSScriptRoot '../scripts/accept-hermes-light-helpers.ps1')
}

Describe 'Hermes Light Scoop update assertions' {
    It 'rejects a no-op update with unchanged current target' {
        $beforeInstall = [ordered]@{
            version = '0.0.0-test-before'
            currentTargetResolved = 'C:\scoop\apps\hermes-agent-light-acceptance\0.0.0-test-before'
        }
        $afterInstall = [ordered]@{
            version = '0.0.0-test-before'
            currentTargetResolved = 'C:\scoop\apps\hermes-agent-light-acceptance\0.0.0-test-before'
        }
        $beforeShortcut = [ordered]@{
            target = 'C:\scoop\apps\hermes-agent-light-acceptance\current\Hermes Light.exe'
            resolvedTarget = 'C:\scoop\apps\hermes-agent-light-acceptance\0.0.0-test-before\Hermes Light.exe'
        }
        $afterShortcut = [ordered]@{
            target = $beforeShortcut.target
            resolvedTarget = $beforeShortcut.resolvedTarget
        }

        {
            Assert-ScoopUpdateSwitch -BeforeInstall $beforeInstall -AfterInstall $afterInstall `
                -BeforeShortcut $beforeShortcut -AfterShortcut $afterShortcut `
                -ExpectedVersion '0.0.1-test-after' `
                -ExpectedCurrentTarget 'C:\scoop\apps\hermes-agent-light-acceptance\0.0.1-test-after' `
                -ExpectedShortcutTarget 'C:\scoop\apps\hermes-agent-light-acceptance\0.0.1-test-after\Hermes Light.exe'
        } | Should -Throw '*no-op*'
    }

    It 'accepts distinct installed versions and changed current target' {
        $beforeInstall = [ordered]@{
            version = '0.0.0-test-before'
            currentTargetResolved = 'C:\scoop\apps\hermes-agent-light-acceptance\0.0.0-test-before'
        }
        $afterInstall = [ordered]@{
            version = '0.0.1-test-after'
            currentTargetResolved = 'C:\scoop\apps\hermes-agent-light-acceptance\0.0.1-test-after'
        }
        $beforeShortcut = [ordered]@{
            target = 'C:\scoop\apps\hermes-agent-light-acceptance\current\Hermes Light.exe'
            resolvedTarget = 'C:\scoop\apps\hermes-agent-light-acceptance\0.0.0-test-before\Hermes Light.exe'
        }
        $afterShortcut = [ordered]@{
            target = $beforeShortcut.target
            resolvedTarget = 'C:\scoop\apps\hermes-agent-light-acceptance\0.0.1-test-after\Hermes Light.exe'
        }

        $result = Assert-ScoopUpdateSwitch -BeforeInstall $beforeInstall -AfterInstall $afterInstall `
            -BeforeShortcut $beforeShortcut -AfterShortcut $afterShortcut `
            -ExpectedVersion '0.0.1-test-after' `
            -ExpectedCurrentTarget 'C:\scoop\apps\hermes-agent-light-acceptance\0.0.1-test-after' `
            -ExpectedShortcutTarget 'C:\scoop\apps\hermes-agent-light-acceptance\0.0.1-test-after\Hermes Light.exe'

        $result.noOpRejected | Should -BeTrue
        $result.beforeVersion | Should -Not -Be $result.afterVersion
        $result.afterVersion | Should -Be '0.0.1-test-after'
        $result.afterCurrentTarget | Should -Be $afterInstall.currentTargetResolved
    }
}

Describe 'Hermes Light Windows runtime classification' {
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
