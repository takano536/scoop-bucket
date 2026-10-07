import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/hermes-light-notices.py'
spec = importlib.util.spec_from_file_location('hermes_light_notices', SCRIPT)
assert spec is not None and spec.loader is not None
notices = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notices)


class NoticeTests(unittest.TestCase):
    def package(
        self,
        root,
        license_name,
        files=None,
        author=None,
        name='fixture-package',
        version='1.0.0',
    ):
        package = root / 'node_modules' / name
        package.mkdir(parents=True)
        metadata = {'name': name, 'version': version, 'license': license_name}
        if author is not None:
            metadata['author'] = author
        (package / 'package.json').write_text(
            json.dumps(metadata), encoding='utf-8'
        )
        for filename, text in (files or {}).items():
            (package / filename).write_text(text, encoding='utf-8')
        return package, metadata

    def override(self, **changes):
        entry = {
            'spdx': 'MIT',
            'copyright': 'Copyright (c) teomyth',
            'evidence': {
                'url': 'https://raw.githubusercontent.com/example/project/'
                '0123456789abcdef0123456789abcdef01234567/README.md',
                'sha256': 'a' * 64,
            },
            'note': 'Reviewed package author attribution.',
        }
        entry.update(changes)
        return {'fixture-package@1.0.0': entry}

    def test_mpl_excerpt_fails_closed(self):
        excerpt = (
            'Mozilla Public License Version 2.0\n\n'
            '1. Definitions\n\n'
            '1.1. Contributor\n\n'
            '1.4. Covered Software\n'
        )
        with tempfile.TemporaryDirectory() as scratch:
            package, metadata = self.package(Path(scratch), 'MPL-2.0', {'LICENSE': excerpt})
            with self.assertRaisesRegex(RuntimeError, 'Incomplete MPL-2.0'):
                notices.license_text(package, metadata, 'fixture-package')

    def test_mit_fallback_without_package_copyright_fails_closed(self):
        with tempfile.TemporaryDirectory() as scratch:
            package, metadata = self.package(Path(scratch), 'MIT', author='Example Author')
            with self.assertRaisesRegex(RuntimeError, 'Cannot determine a license text'):
                notices.license_text(package, metadata, 'fixture-package')

    def test_apache_notice_without_license_fails_closed(self):
        with tempfile.TemporaryDirectory() as scratch:
            package, metadata = self.package(
                Path(scratch),
                'Apache-2.0',
                {'NOTICE': 'Copyright 2025 Example contributors'},
            )
            with self.assertRaisesRegex(RuntimeError, 'NOTICE without a LICENSE'):
                notices.license_text(package, metadata, 'fixture-package')

    def test_license_override_applies_on_exact_match(self):
        with tempfile.TemporaryDirectory() as scratch:
            package, metadata = self.package(Path(scratch), 'MIT')
            used = set()
            license_name, text = notices.license_text(
                package,
                metadata,
                'fixture-package',
                self.override(),
                used,
            )
            self.assertEqual(license_name, 'MIT')
            self.assertEqual(used, {'fixture-package@1.0.0'})
            self.assertIn('License text reconstructed from the declared SPDX license', text)
            self.assertIn('Copyright (c) teomyth', text)
            self.assertIn('Evidence source:', text)
            self.assertIn('Permission is hereby granted', text)

    def test_license_override_does_not_replace_empty_license_file(self):
        with tempfile.TemporaryDirectory() as scratch:
            package, metadata = self.package(Path(scratch), 'MIT', {'LICENSE': ''})
            with self.assertRaisesRegex(RuntimeError, 'Cannot determine a license text'):
                notices.license_text(package, metadata, 'fixture-package', self.override())

    def test_license_override_version_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as scratch:
            package, metadata = self.package(Path(scratch), 'MIT', version='1.0.1')
            with self.assertRaisesRegex(RuntimeError, 'Cannot determine a license text'):
                notices.license_text(package, metadata, 'fixture-package', self.override())

    def test_license_override_spdx_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as scratch:
            package, metadata = self.package(Path(scratch), 'MIT')
            with self.assertRaisesRegex(RuntimeError, 'SPDX mismatch'):
                notices.license_text(
                    package,
                    metadata,
                    'fixture-package',
                    self.override(spdx='Apache-2.0'),
                )

    def test_unused_license_override_fails(self):
        with self.assertRaisesRegex(RuntimeError, 'Unused license override entries'):
            notices.validate_unused_overrides(self.override(), set())

    def test_collect_packages_reports_all_license_failures(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            source = root / 'source'
            desktop = source / 'apps' / 'desktop'
            node_modules = desktop / 'node_modules'
            node_modules.mkdir(parents=True)
            (desktop / 'package.json').write_text(
                json.dumps(
                    {
                        'name': 'desktop',
                        'version': '1.0.0',
                        'dependencies': {
                            'fixture-one': '1.0.0',
                            'fixture-two': '1.0.0',
                        },
                    }
                ),
                encoding='utf-8',
            )
            for name in ('fixture-one', 'fixture-two'):
                package = node_modules / name
                package.mkdir()
                (package / 'package.json').write_text(
                    json.dumps(
                        {
                            'name': name,
                            'version': '1.0.0',
                            'license': 'MIT',
                        }
                    ),
                    encoding='utf-8',
                )
            with patch.object(notices, 'load_license_overrides', return_value={}), patch.object(
                notices, 'asar_node_modules', return_value=set()
            ):
                with self.assertRaisesRegex(
                    RuntimeError, 'License validation failed for shipped packages'
                ) as raised:
                    notices.collect_packages(source, root / 'pack')
            message = str(raised.exception)
            self.assertIn('fixture-one@1.0.0', message)
            self.assertIn('fixture-two@1.0.0', message)
            self.assertLess(message.index('fixture-one@1.0.0'), message.index('fixture-two@1.0.0'))

    def test_unknown_or_missing_license_fails_closed(self):
        for license_name in ('Custom-License', ''):
            with self.subTest(license_name=license_name), tempfile.TemporaryDirectory() as scratch:
                package, metadata = self.package(Path(scratch), license_name)
                with self.assertRaisesRegex(RuntimeError, 'Cannot determine a license text'):
                    notices.license_text(package, metadata, 'fixture-package')

    def test_full_mit_license_variant_with_copyright_passes(self):
        full_mit = '''MIT License

Copyright (c) 2025 Example contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is furnished
to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''
        with tempfile.TemporaryDirectory() as scratch:
            package, metadata = self.package(
                Path(scratch),
                'MIT',
                {'LICENSE-MIT': full_mit},
                author='Example Author',
            )
            license_name, text = notices.license_text(package, metadata, 'fixture-package')
            self.assertEqual(license_name, 'MIT')
            self.assertIn('[LICENSE-MIT]', text)
            self.assertIn('Copyright (c) 2025 Example contributors', text)


if __name__ == '__main__':
    unittest.main()
