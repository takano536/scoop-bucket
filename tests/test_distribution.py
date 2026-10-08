"""Application-scoped distribution identity and numeric revision ordering."""
import subprocess
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import distribution
_LEGACY_IDENTIFIERS = (
    'hermes-agent-' + 'light',
    'hermes-' + 'light',
    'HERMES_' + 'LIGHT_RELEASE_ENABLED',
    'Hermes ' + 'Light',
)
_UPSTREAM_ALLOWLIST = {
    'scripts/build-hermes-desktop-light.ps1': {
        'hermes-' + 'light': (
            'if ($env:PREVIEW -eq \'' + 'true' + '\') { $exeName = "' +
            'hermes-' + 'light' + '-$($commit.Substring(0, 7)).exe" }',
        ),
    },
    'scripts/hermes-desktop-light.py': {
        'hermes-' + 'light': (
            "'" + 'hermes-' + 'light' + "',",
        ),
    },
    'tests/test_hermes_desktop_light.py': {
        'hermes-' + 'light': (
            'self.identity = {\'content\': base64.b64encode(b"light: { kebab: \'' +
            'hermes-' + 'light' + '\' }\\nHERMES_BUILD_COMMIT\\nwindowsExecutableName").decode()}',
        ),
    },
}
_LEGACY_EXECUTABLE_PATHS = {
    'scripts/build-hermes-desktop-light.ps1',
    'scripts/hermes-desktop-light.py',
    'tests/autoupdate-fixture-server.py',
    'tests/autoupdate-regression.ps1',
    'tests/test_hermes_desktop_light.py',
}


def _legacy_distribution_occurrences():
    tracked = subprocess.check_output(
        ['git', '-C', str(ROOT), 'ls-files', '-z'], text=False
    ).split(b'\0')
    violations = []
    for raw_path in tracked:
        if not raw_path:
            continue
        relative = raw_path.decode('utf-8')
        if any(identifier in relative for identifier in _LEGACY_IDENTIFIERS):
            violations.append(f'{relative} (tracked path)')
            continue
        try:
            text = (ROOT / relative).read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            for identifier in _LEGACY_IDENTIFIERS:
                if identifier not in line:
                    continue
                allowed = _UPSTREAM_ALLOWLIST.get(relative, {}).get(identifier, ())
                if stripped in allowed:
                    continue
                if (identifier == 'hermes-' + 'light' and
                        relative in _LEGACY_EXECUTABLE_PATHS and
                        (identifier + '-') in line):
                    continue
                if identifier == 'Hermes ' + 'Light' and (identifier + '.exe') in line:
                    continue
                violations.append(f'{relative}:{line_number}: {line}')
    return violations



class DistributionTests(unittest.TestCase):
    def test_scoped_tags_and_revision_order(self):
        self.assertEqual(distribution.release_tag('hermes-desktop-light', '0.22.0-r1'), 'hermes-desktop-light/v0.22.0-r1')
        self.assertNotEqual(distribution.release_tag('other-app', '0.22.0-r1'), distribution.release_tag('hermes-desktop-light', '0.22.0-r1'))
        self.assertLess(distribution.version_key('0.22.0-r2'), distribution.version_key('0.22.0-r10'))
        self.assertLess(distribution.version_key('0.22.0-r10'), distribution.version_key('0.23.0-r1'))
        self.assertEqual(distribution.package_version('0.22.0', '2'), '0.22.0-r2')

    def test_development_identity_and_order_are_numeric(self):
        commit = 'a' * 40
        first = distribution.dev_package_version(9, 1)
        next_sequence = distribution.dev_package_version(10, 1)
        next_revision = distribution.dev_package_version(9, 2)
        self.assertEqual(
            distribution.dev_release_tag('hermes-desktop-light', first, commit),
            f'hermes-desktop-light/dev/v{first}-{commit}',
        )
        self.assertEqual(
            distribution.dev_artifact_name('hermes-desktop-light', first, commit),
            f'hermes-desktop-light-dev-{first}-{commit}-windows-x64.zip',
        )
        self.assertLess(distribution.distribution_version_key(first),
                        distribution.distribution_version_key(next_sequence))
        self.assertLess(distribution.distribution_version_key(first),
                        distribution.distribution_version_key(next_revision))
        self.assertLess(distribution.distribution_version_key(first),
                        distribution.distribution_version_key('0.0.0-r1'))
        self.assertLess(distribution.distribution_version_key(first),
                        distribution.distribution_version_key('2026.9.24-r1'))
        self.assertLess(distribution.distribution_version_key('0.0.0-r1'),
                        distribution.distribution_version_key('2026.10.1-r1'))

    def test_development_identities_fail_closed(self):
        commit = 'a' * 40
        for version in ('0.0.0-alpha.dev.0-r1', '0.0.0-alpha.dev.1-r0',
                        '0.0.0-alpha.dev.01-r1', '0.0.0.dev.1-r1'):
            with self.assertRaises(ValueError):
                distribution.dev_version_key(version)
        with self.assertRaises(ValueError):
            distribution.dev_release_tag('Hermes', '0.0.0-alpha.dev.1-r1', commit)
        with self.assertRaises(ValueError):
            distribution.dev_artifact_name('hermes-desktop-light', '0.0.0-alpha.dev.1-r1', 'bad')

    def test_invalid_identities_fail_closed(self):
        for version in ('0.22.0', '0.22.0-r0', '0.22.0-r01', '0.22.0-rc.1', '../0.22.0-r1'):
            with self.assertRaises(ValueError):
                distribution.version_key(version)
        for app in ('../escape', 'app/name', 'UPPER'):
            with self.assertRaises(ValueError):
                distribution.release_tag(app, '0.22.0-r1')
        for revision in ('0', '01', '-1', 'x'):
            with self.assertRaises(ValueError):
                distribution.package_version('0.22.0', revision)

    def test_legacy_distribution_names_are_absent(self):
        self.assertEqual(_legacy_distribution_occurrences(), [])


if __name__ == '__main__':
    unittest.main()
