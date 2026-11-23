BeforeAll {
    . (Join-Path $PSScriptRoot '../scripts/installed-payload.ps1')
}

Describe 'Test-InstalledPayload' {
    BeforeEach {
        $script:root = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $script:root -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $script:root 'scoop-manifest.json') -Value '{}'
        Set-Content -LiteralPath (Join-Path $script:root 'install.json') -Value '{"architecture":"64bit"}'
    }

    It 'accepts an app whose declared targets exist' {
        Set-Content -LiteralPath (Join-Path $script:root 'Meltype.exe') -Value ''
        New-Item -ItemType Directory -Path (Join-Path $script:root 'tip') | Out-Null
        $manifest = '{"shortcuts":[["Meltype.exe","Meltype"]],"bin":["Meltype.exe"]}' | ConvertFrom-Json

        @(Test-InstalledPayload -Prefix $script:root -Manifest $manifest) | Should -BeNullOrEmpty
    }

    It 'reports a shortcut target that the archive no longer contains' {
        Set-Content -LiteralPath (Join-Path $script:root 'Meltype-1.7.1-setup.exe') -Value ''
        Set-Content -LiteralPath (Join-Path $script:root 'install.ps1') -Value ''
        $manifest = '{"shortcuts":[["app\\Meltype.exe","Meltype"]]}' | ConvertFrom-Json

        $problems = @(Test-InstalledPayload -Prefix $script:root -Manifest $manifest)

        $problems | Should -Contain 'shortcut target was not installed: app\Meltype.exe'
    }

    It 'reports an app directory that only has Scoop metadata' {
        $manifest = '{}' | ConvertFrom-Json

        $problems = @(Test-InstalledPayload -Prefix $script:root -Manifest $manifest)

        $problems | Should -Contain 'installed app directory contains no files besides Scoop metadata'
    }

    It 'uses the architecture specific target' {
        Set-Content -LiteralPath (Join-Path $script:root 'tool.exe') -Value ''
        $manifest = '{"shortcuts":[["tool.exe","Tool"]],"architecture":{"64bit":{"bin":["x64\\missing.exe"]}}}' | ConvertFrom-Json

        $problems = @(Test-InstalledPayload -Prefix $script:root -Manifest $manifest -Architecture '64bit')

        $problems | Should -Contain 'bin target was not installed: x64\missing.exe'
    }

    It 'skips installer manifests' {
        $manifest = '{"installer":{"script":["exit 0"]}}' | ConvertFrom-Json

        @(Test-InstalledPayload -Prefix $script:root -Manifest $manifest) | Should -BeNullOrEmpty
    }
}
