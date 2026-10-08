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
