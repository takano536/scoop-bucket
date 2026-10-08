import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/hermes-desktop-light-notices.py'
spec = importlib.util.spec_from_file_location('hermes_desktop_light_notices', SCRIPT)
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
        package = root / 'node_modules'
        if name.startswith('@'):
            package = package / name.split('/', 1)[0] / name.split('/', 1)[1]
        else:
            package = package / name
        package.mkdir(parents=True)
        metadata = {'name': name, 'version': version}
        if license_name is not None:
            metadata['license'] = license_name
        if author is not None:
            metadata['author'] = author
        (package / 'package.json').write_text(
            json.dumps(metadata), encoding='utf-8'
        )
        for filename, text in (files or {}).items():
            target = package / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8')
        return package, metadata

    def override(self, **changes):
        entry = {
            'spdx': 'MIT',
            'copyright': 'Copyright (c) teomyth',
            'evidence': {
                'kind': 'attribution',
                'url': 'https://raw.githubusercontent.com/example/project/'
                '0123456789abcdef0123456789abcdef01234567/README.md',
                'path': 'README.md',
                'sha256': hashlib.sha256(b'Readme evidence').hexdigest(),
                'retrieval': 'fixture evidence retrieval',
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
        with tempfile.TemporaryDirectory() as scratch, patch.object(
            notices, 'fetch_evidence', return_value=b'Readme evidence'
        ):
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

    def test_license_override_sha256_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as scratch, patch.object(
            notices, 'fetch_evidence', return_value=b'not the reviewed bytes'
        ):
            package, metadata = self.package(Path(scratch), 'MIT')
            with self.assertRaisesRegex(RuntimeError, 'evidence SHA256 mismatch'):
                notices.license_text(package, metadata, 'fixture-package', self.override())

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

    def test_license_override_reconstructs_missing_declaration_from_license_evidence(self):
        content = (
            'The MIT License (MIT)\n\n'
            'Copyright (c) 2019-present Fabio Spampinato, Andrew Maney\n\n'
            'Permission is hereby granted, free of charge, to any person obtaining a copy\n'
            'of this software and associated documentation files (the "Software"), to deal\n'
            'in the Software without restriction, including without limitation the rights\n'
            'to use, copy, modify, merge, publish, distribute, sublicense, and/or sell\n'
            'copies of the Software, and to permit persons to whom the Software is\n'
            'furnished to do so, subject to the following conditions:\n\n'
            'The above copyright notice and this permission notice shall be included in all\n'
            'copies or substantial portions of the Software.\n\n'
            'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.\n'
        )
        evidence = {
            'kind': 'license',
            'url': 'https://raw.githubusercontent.com/example/project/'
            '0123456789abcdef0123456789abcdef01234567/license',
            'path': 'package/license',
            'sha256': hashlib.sha256(content.encode()).hexdigest(),
            'retrieval': 'fixture tarball and upstream source retrieval',
        }
        with tempfile.TemporaryDirectory() as scratch, patch.object(
            notices, 'fetch_evidence', return_value=content.encode()
        ):
            package, metadata = self.package(
                Path(scratch), None, {'license': content}, name='khroma', version='2.1.0'
            )
            overrides = {'khroma@2.1.0': {
                'spdx': 'MIT',
                'copyright': 'Copyright (c) 2019-present Fabio Spampinato, Andrew Maney',
                'evidence': evidence,
                'note': 'Exact tarball license fixture.',
            }}
            license_name, text = notices.license_text(
                package, metadata, 'khroma', overrides, set()
            )
            self.assertEqual(license_name, 'MIT')
            self.assertIn('License text reproduced from the cited immutable license source.', text)
            self.assertIn('Copyright (c) 2019-present Fabio Spampinato, Andrew Maney', text)

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
                        'dependencies': {},
                        'devDependencies': {
                            'fixture-one': '1.0.0',
                            'fixture-two': '1.0.0',
                            'build-tool': '1.0.0',
                        },
                    }
                ),
                encoding='utf-8',
            )
            for name in ('fixture-one', 'fixture-two', 'build-tool'):
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
            bundle_graph = {
                'packages': [
                    {
                        'name': name,
                        'path': f'apps/desktop/node_modules/{name}',
                    }
                    for name in ('fixture-one', 'fixture-two')
                ]
            }
            with patch.object(notices, 'load_license_overrides', return_value={}), patch.object(
                notices, 'asar_node_modules', return_value=set()
            ):
                with self.assertRaisesRegex(
                    RuntimeError, 'License validation failed for shipped packages'
                ) as raised:
                    notices.collect_packages(source, root / 'pack', bundle_graph)
            message = str(raised.exception)
            self.assertIn('fixture-one@1.0.0', message)
            self.assertIn('fixture-two@1.0.0', message)
            self.assertLess(message.index('fixture-one@1.0.0'), message.index('fixture-two@1.0.0'))
            self.assertNotIn('build-tool@1.0.0', message)

    def test_bundled_dev_dependency_is_detected_from_source_map(self):
        mit = (
            'MIT License\n\nCopyright (c) 2025 Bundle Author\n\n'
            'Permission is hereby granted, free of charge, to any person obtaining a copy\n'
            'of this software and associated documentation files (the "Software"), to deal\n'
            'in the Software without restriction, including without limitation the rights\n'
            'to use, copy, modify, merge, publish, distribute, sublicense, and/or sell\n'
            'copies of the Software, and to permit persons to whom the Software is\n'
            'furnished to do so, subject to the following conditions:\n\n'
            'The above copyright notice and this permission notice shall be included in all\n'
            'copies or substantial portions of the Software.\n\n'
            'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\n'
            'IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,\n'
            'FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.\n'
        )
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            source = root / 'source'
            desktop = source / 'apps' / 'desktop'
            package = desktop / 'node_modules' / 'bundled-only'
            package.mkdir(parents=True)
            (desktop / 'package.json').write_text(
                json.dumps({'name': 'desktop', 'version': '1.0.0', 'devDependencies': {'bundled-only': '1.0.0'}}),
                encoding='utf-8',
            )
            (package / 'package.json').write_text(
                json.dumps({'name': 'bundled-only', 'version': '1.0.0', 'license': 'MIT'}),
                encoding='utf-8',
            )
            (package / 'LICENSE').write_text(mit, encoding='utf-8')
            dist = desktop / 'dist' / 'assets'
            dist.mkdir(parents=True)
            (dist / 'index.js.map').write_text(
                json.dumps({'version': 3, 'sources': ['../../node_modules/bundled-only/index.js']}),
                encoding='utf-8',
            )
            bundle_graph = notices.bundle_module_graph(source)
            with patch.object(notices, 'load_license_overrides', return_value={}), patch.object(
                notices, 'asar_node_modules', return_value=set()
            ):
                packages = notices.collect_packages(source, root / 'pack', bundle_graph)
            self.assertEqual(
                [(name, version) for name, version, *_ in packages],
                [('bundled-only', '1.0.0')],
            )

    def test_bundle_module_graph_missing_fails_closed(self):
        with tempfile.TemporaryDirectory() as scratch:
            source = Path(scratch) / 'source'
            (source / 'apps' / 'desktop' / 'dist').mkdir(parents=True)
            with self.assertRaisesRegex(RuntimeError, 'Cannot obtain bundled module graph'):
                notices.bundle_module_graph(source)

    def test_unpacked_node_modules_reports_resources_packages(self):
        with tempfile.TemporaryDirectory() as scratch:
            resources = Path(scratch) / 'pack' / 'resources'
            unpacked = resources / 'app.asar.unpacked' / 'dist' / 'node_modules'
            scoped = resources / 'node_modules' / '@fixture'
            (unpacked / 'node-pty').mkdir(parents=True)
            (scoped / 'resource-tool').mkdir(parents=True)
            (unpacked / 'node-pty' / 'package.json').write_text('{}', encoding='utf-8')
            (scoped / 'resource-tool' / 'package.json').write_text('{}', encoding='utf-8')
            self.assertEqual(
                notices.unpacked_node_modules(Path(scratch) / 'pack'),
                {'node-pty', '@fixture/resource-tool'},
            )

    def test_unknown_or_missing_license_fails_closed(self):
        for license_name in ('Custom-License', ''):
            with self.subTest(license_name=license_name), tempfile.TemporaryDirectory() as scratch:
                package, metadata = self.package(Path(scratch), license_name)
                with self.assertRaisesRegex(RuntimeError, 'Cannot determine a license text'):
                    notices.license_text(package, metadata, 'fixture-package')

    def test_reconstructed_mit_without_copyright_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'no package-specific copyright'):
            notices.validate_license_text('MIT', notices.MIT_LICENSE_TEXT, 'fixture-package')

    def test_package_supplied_complete_mit_without_holder_is_retained(self):
        with tempfile.TemporaryDirectory() as scratch:
            package, metadata = self.package(
                Path(scratch), 'MIT', {'LICENSE': notices.MIT_LICENSE_TEXT}
            )
            license_name, text = notices.license_text(package, metadata, 'fixture-package')
            self.assertEqual(license_name, 'MIT')
            self.assertIn('Permission is hereby granted', text)

    def test_package_supplied_mit_placeholder_fails_closed(self):
        placeholder = notices.MIT_LICENSE_TEXT.replace(
            'MIT License\n\n', 'MIT License\n\nCopyright (c) [year] [fullname]\n\n', 1
        )
        with tempfile.TemporaryDirectory() as scratch:
            package, metadata = self.package(Path(scratch), 'MIT', {'LICENSE': placeholder})
            with self.assertRaisesRegex(RuntimeError, 'placeholder copyright'):
                notices.license_text(package, metadata, 'fixture-package')

    def test_non_line_start_and_multi_holder_copyright_passes(self):
        full_mit = '''(MIT)\n\nOriginal code Copyright Julian Gruber <julian@juliangruber.com>\nPort to TypeScript Copyright Isaac Z. Schlueter <i@izs.me>\n\nPermission is hereby granted, free of charge, to any person obtaining a copy\nof this software and associated documentation files (the "Software"), to deal\nin the Software without restriction, including without limitation the rights\nto use, copy, modify, merge, publish, distribute, sublicense, and/or sell\ncopies of the Software, and to permit persons to whom the Software is\nfurnished to do so, subject to the following conditions:\n\nThe above copyright notice and this permission notice shall be included in all\ncopies or substantial portions of the Software.\n\nTHE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\nIMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,\nFITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.\n'''
        with tempfile.TemporaryDirectory() as scratch:
            package, metadata = self.package(Path(scratch), 'MIT', {'LICENSE.md': full_mit})
            license_name, text = notices.license_text(package, metadata, 'fixture-package')
            self.assertEqual(license_name, 'MIT')
            self.assertIn('Original code Copyright Julian Gruber', text)

    def test_package_supplied_short_mit_notice_with_disclaimer_passes(self):
        short_mit = '''Dijkstra path-finding functions.

Copyright (C) 2008 Wyatt Baldwin

Licensed under the MIT license.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
'''
        with tempfile.TemporaryDirectory() as scratch:
            package, metadata = self.package(Path(scratch), 'MIT', {'LICENSE.md': short_mit})
            license_name, text = notices.license_text(package, metadata, 'fixture-package')
            self.assertEqual(license_name, 'MIT')
            self.assertIn('Licensed under the MIT license', text)

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

    def test_novnc_mpl_notice_includes_source_availability(self):
        mpl = '\n\n'.join(notices.MPL_REQUIRED_MARKERS) + '\n'
        with tempfile.TemporaryDirectory() as scratch:
            package, metadata = self.package(
                Path(scratch), 'MPL-2.0', {
                    'LICENSE.txt': mpl,
                    'docs/LICENSE.BSD-2-Clause': 'BSD-2-Clause vendored notice',
                    'docs/LICENSE.BSD-3-Clause': 'BSD-3-Clause vendored notice',
                    'docs/LICENSE.OFL-1.1': 'OFL-1.1 vendored notice',
                    'vendor/pako/LICENSE': 'MIT License\n\nCopyright (C) 2014-2016 by Vitaly Puzrin\n\nPermission is hereby granted',
                },
                name='@novnc/novnc', version='1.7.0'
            )
            _, text = notices.license_text(
                package, metadata, '@novnc/novnc', source_origins={'bundle-map'}
            )
            self.assertIn('MPL-2.0 Source Code Form availability', text)
            self.assertIn(
                'inlined and minified into the renderer bundle; no unmodified '
                '@novnc/novnc node_modules directory was shipped.',
                text,
            )
            self.assertIn('novnc-1.7.0.tgz', text)
            self.assertIn('63107bd06d9e1f6136ff21aeda8cd62cbf0d433e', text)

            for path in (
                'docs/LICENSE.BSD-2-Clause',
                'docs/LICENSE.BSD-3-Clause',
                'docs/LICENSE.OFL-1.1',
                'vendor/pako/LICENSE',
            ):
                self.assertIn(f'[{path}]', text)

if __name__ == '__main__':
    unittest.main()
