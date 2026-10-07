param([Parameter(Mandatory)][string]$ScoopHome)
$ErrorActionPreference = 'Stop'
$validator = Join-Path $PSScriptRoot '../bin/test-autoupdate.ps1'
if (!(Test-Path $validator)) { throw 'Autoupdate validator is missing' }
$root = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString())
New-Item $root -ItemType Directory | Out-Null
$server = $null
try {
    $server = Start-Process python -ArgumentList @((Join-Path $PSScriptRoot 'autoupdate-fixture-server.py'), $root) -PassThru -NoNewWindow
    $ready = Join-Path $root 'port.txt'
    $deadline = (Get-Date).AddSeconds(30)
    while (!(Test-Path $ready)) {
        if ($server.HasExited -or (Get-Date) -gt $deadline) { throw 'Fixture server did not start' }
        Start-Sleep -Milliseconds 100
    }
    $base = 'http://127.0.0.1:' + (Get-Content $ready -Raw).Trim()
    $manifest = @{
        version = '2.0.0'; homepage = $base; license = 'MIT'; description = 'Test fixture'
        url = "$base/app-2.0.0.zip"; hash = (Invoke-RestMethod "$base/hash").Trim()
        extract_dir = 'app-2.0.0'
        checkver = @{ url = "$base/latest"; regex = 'v([\d.]+)' }
        autoupdate = @{ url = "$base/app-`$version.zip"; extract_dir = 'app-$version' }
    }
    $cases = @(
        @{ Name = 'valid-current-version'; Fails = $false; Mutate = {} },
        @{ Name = 'missing-checkver'; Fails = $true; Mutate = { param($m) $m.Remove('checkver') } },
        @{ Name = 'missing-autoupdate'; Fails = $true; Mutate = { param($m) $m.Remove('autoupdate') } },
        @{ Name = 'unmatched-regex'; Fails = $true; Mutate = { param($m) $m.checkver.regex = 'NEVER_MATCH_(\d+)' } },
        @{ Name = 'unreachable-checkver'; Fails = $true; Mutate = { param($m) $m.checkver.url = "$base/missing" } },
        @{ Name = 'wrong-download-url'; Fails = $true; Mutate = { param($m) $m.autoupdate.url = "$base/missing-`$version.zip" } },
        @{ Name = 'unresolved-placeholder'; Fails = $true; Mutate = { param($m) $m.autoupdate.extract_dir = 'app-$versoin' } },
        @{ Name = 'fixed-version-url'; Fails = $true; Mutate = { param($m) $m.autoupdate.url = "$base/app-2.0.0.zip" } },
        @{ Name = 'fixed-version-extract-dir'; Fails = $true; Mutate = { param($m) $m.autoupdate.extract_dir = 'app-2.0.0' } },
        @{ Name = 'missing-url-template'; Fails = $true; Mutate = { param($m) $m.autoupdate.Remove('url') } },
        @{ Name = 'incorrect-hash'; Fails = $true; Mutate = { param($m) $m.hash = '0' * 64 } },
        @{ Name = 'incorrect-upstream-hash'; Fails = $true; Mutate = { param($m) $m.version = '1.0.0'; $m.autoupdate.hash = @{ url = "$base/bad-hash"; regex = '^([a-f0-9]{64})$' } } },
        @{ Name = 'wrong-extract-dir'; Fails = $true; Mutate = { param($m) $m.version = '1.0.0'; $m.autoupdate.extract_dir = 'nonexistent' } },
        @{ Name = 'stale-manifest'; Fails = $false; Mutate = { param($m) $m.version = '1.0.0'; $m.url = "$base/app-1.0.0.zip"; $m.extract_dir = 'app-1.0.0' } }
    )
    foreach ($case in $cases) {
        $dir = Join-Path $root $case.Name
        New-Item $dir -ItemType Directory | Out-Null
        $copy = $manifest | ConvertTo-Json -Depth 20 | ConvertFrom-Json -AsHashtable
        & $case.Mutate $copy
        $file = Join-Path $dir 'fixture.json'
        $copy | ConvertTo-Json -Depth 20 | Set-Content $file -Encoding utf8
        $before = (Get-FileHash $file).Hash
        $failed = $false
        try { & $validator -ScoopHome $ScoopHome -BucketDir $dir } catch { $failed = $true; Write-Host "Expected rejection: $_" }
        if ($failed -ne $case.Fails) { throw "Unexpected result: $($case.Name), rejected=$failed" }
        if ((Get-FileHash $file).Hash -ne $before) { throw 'Validator modified the original manifest' }
        Write-Host "PASS $($case.Name)"
    }
    Write-Host "Passed $($cases.Count) autoupdate regression cases"
} finally {
    if ($server -and !$server.HasExited) { Stop-Process -Id $server.Id -Force }
    Remove-Item $root -Recurse -Force
}
