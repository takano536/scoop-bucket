import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/hermes-desktop-light.py'


class ReleaseTests(unittest.TestCase):
    def test_only_published_stable_semver_is_admitted(self):
        self.assertTrue(SCRIPT.exists(), 'Desktop Light release helper is missing')
        spec = importlib.util.spec_from_file_location('light', SCRIPT)
        assert spec is not None and spec.loader is not None
        light = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(light)
        self.assertEqual(light.stable_version({'tag_name': 'v0.22.0', 'draft': False, 'prerelease': False}), '0.22.0')
        for tag in ('v2026.9.24', 'v0.22.0-rc.1', 'v0.22.0+canary.20261007T000000Z', 'main', 'v00.22.0'):
            self.assertIsNone(light.stable_version({'tag_name': tag, 'draft': False, 'prerelease': False}))
        self.assertIsNone(light.stable_version({'tag_name': 'v0.22.0', 'draft': False, 'prerelease': True}))
        self.assertIsNone(light.stable_version({'tag_name': 'v0.22.0', 'draft': True, 'prerelease': False}))

    def test_historical_calver_is_explicitly_skipped(self):
        from unittest.mock import Mock, patch
        spec = importlib.util.spec_from_file_location('light', SCRIPT)
        assert spec is not None and spec.loader is not None
        light = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(light)
        output = Mock()
        with patch.object(light, 'api', return_value={
                'tag_name': 'v2026.9.24', 'draft': False, 'prerelease': False}), \
                patch.object(light, 'output', output), patch('builtins.print') as printed:
            light.plan()
        output.assert_called_once_with(build='false')
        self.assertIn('historical CalVer', printed.call_args.args[0])


    def test_manifest_binds_version_repository_and_exact_bytes(self):
        spec = importlib.util.spec_from_file_location('light', SCRIPT)
        assert spec is not None and spec.loader is not None
        light = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(light)
        self.assertTrue(hasattr(light, 'manifest'), 'Manifest generation is missing')
        result = light.manifest('0.22.0-r1', 'takano536/scoop-bucket', 'a' * 64)
        self.assertEqual(result['version'], '0.22.0-r1')
        self.assertEqual(result['architecture']['64bit']['hash'], 'a' * 64)
        self.assertEqual(result['architecture']['64bit']['url'], 'https://github.com/takano536/scoop-bucket/releases/download/hermes-desktop-light%2Fv0.22.0-r1/hermes-desktop-light-0.22.0-r1-windows-x64.zip')
        self.assertEqual(result['autoupdate']['architecture']['64bit']['url'], 'https://github.com/takano536/scoop-bucket/releases/download/hermes-desktop-light%2Fv$version/hermes-desktop-light-$version-windows-x64.zip')
        self.assertEqual(result['shortcuts'][0][0], 'Hermes Light.exe')
        for version, repository, digest in [('0.22.0-rc.1', 'a/b', 'a' * 64), ('0.22.0-r1', 'bad', 'a' * 64), ('0.22.0-r1', 'a/b', 'bad')]:
            with self.assertRaises(ValueError):
                light.manifest(version, repository, digest)


    def test_release_claim_requires_exact_commit_and_annotated_object(self):
        spec = importlib.util.spec_from_file_location('light', SCRIPT)
        assert spec is not None and spec.loader is not None
        light = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(light)
        self.assertTrue(hasattr(light, 'release_claim'), 'Claim validation is missing')
        record = {'version': '0.22.0', 'commit': 'a' * 40, 'claimTag': 'rc.1-v0.22.0', 'claimTagObject': 'b' * 40}
        self.assertEqual(light.release_claim(record, '0.22.0', 'a' * 40), ('rc.1-v0.22.0', 'b' * 40))
        for change in ({'commit': 'c' * 40}, {'version': '0.21.0'}, {'claimTag': 'main'}, {'claimTagObject': 'bad'}):
            with self.assertRaises(ValueError):
                light.release_claim({**record, **change}, '0.22.0', 'a' * 40)


    def test_receipt_rejects_preview_tampering_and_missing_notices(self):
        import hashlib
        import tempfile
        import zipfile
        spec = importlib.util.spec_from_file_location('light', SCRIPT)
        assert spec is not None and spec.loader is not None
        light = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(light)
        self.assertTrue(hasattr(light, 'verify_artifact'), 'Artifact validation is missing')
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            artifact = root / 'hermes-desktop-light-0.22.0-r1-windows-x64.zip'
            files = {
                'LICENSE': 'MIT License\n\nCopyright (c) 2025 Nous Research\n',
                'LICENSE.electron.txt': 'Electron license fixture',
                'LICENSES.chromium.html': '<html>Chromium license fixture</html>',
                'THIRD-PARTY-NOTICES.txt': 'Package fixture: MIT\n',
                'UNOFFICIAL-BUILD.txt': 'Unofficial unsigned build fixture\n',
            }
            with zipfile.ZipFile(artifact, 'w') as archive:
                archive.writestr('Hermes Light.exe', b'test fixture')
                archive.writestr('resources/app.asar', b'test fixture')
                archive.writestr('resources/install-stamp.json', '{"payload":"light","updateMechanism":"external","commit":"' + 'a' * 40 + '"}')
                for name, content in files.items():
                    archive.writestr(name, content)
            notices = {
                'upstreamLicense': {'path': 'LICENSE', 'sha256': hashlib.sha256(files['LICENSE'].encode()).hexdigest()},
                'thirdParty': {
                    'path': 'THIRD-PARTY-NOTICES.txt',
                    'sha256': hashlib.sha256(files['THIRD-PARTY-NOTICES.txt'].encode()).hexdigest(),
                    'packages': 1,
                },
                'unofficial': {'path': 'UNOFFICIAL-BUILD.txt', 'sha256': hashlib.sha256(files['UNOFFICIAL-BUILD.txt'].encode()).hexdigest()},
            }
            record = dict(schema=1, upstream='NousResearch/hermes-agent', sourceRef='v0.22.0', version='0.22.0-r1', commit='a' * 40, preview=False, artifact=artifact.name, sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(), payload='light', updateMechanism='external', executable='Hermes Light.exe', smoke='two native launches; renderer loaded; localStorage retained', notices=notices)
            self.assertEqual(light.verify_artifact(root, record, '0.22.0-r1', 'v0.22.0'), artifact)
            valid_bytes = artifact.read_bytes()
            with zipfile.ZipFile(artifact, 'w') as archive:
                for name, content in files.items():
                    if name != 'THIRD-PARTY-NOTICES.txt':
                        archive.writestr(name, content)
                archive.writestr('Hermes Light.exe', b'test fixture')
                archive.writestr('resources/app.asar', b'test fixture')
                archive.writestr('resources/install-stamp.json', '{"payload":"light","updateMechanism":"external","commit":"' + 'a' * 40 + '"}')
            with self.assertRaisesRegex(ValueError, 'Invalid Light package contents'):
                light.verify_artifact(root, {**record, 'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()}, '0.22.0-r1', 'v0.22.0')
            artifact.write_bytes(valid_bytes)
            for change in ({'preview': True}, {'sha256': 'b' * 64}, {'version': '0.21.0'}, {'commit': 'b' * 40}, {'artifact': '../escape.zip'}, {'smoke': 'not run'}, {'notices': {}}):
                with self.assertRaises(ValueError):
                    light.verify_artifact(root, {**record, **change}, '0.22.0-r1', 'v0.22.0')


class PlanTests(unittest.TestCase):
    def setUp(self):
        import base64
        from unittest.mock import Mock
        spec = importlib.util.spec_from_file_location('light_plan', SCRIPT)
        assert spec is not None and spec.loader is not None
        self.light = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.light)
        self.commit = 'a' * 40
        self.identity = {'content': base64.b64encode(b"light: { kebab: 'hermes-light' }").decode()}
        self.builder = {'content': base64.b64encode(b'parser.add_argument("--variant", choices=["bundled", "light"])').decode()}
        self.calls = []
        self.result = Mock()

    def run_plan(self, response, preview=False):
        from unittest.mock import patch
        import os
        def api(endpoint):
            self.calls.append(endpoint)
            return response(endpoint)
        with patch.dict(os.environ, {'PREVIEW': str(preview).lower()}), patch.object(self.light, 'api', side_effect=api), patch.object(self.light, 'output', self.result):
            self.light.plan()

    def response(self, endpoint):
        import json
        if endpoint.endswith('/releases/latest'):
            return {'tag_name': 'v0.22.0', 'draft': False, 'prerelease': False}
        if '/commits/' in endpoint:
            return {'sha': self.commit}
        if '/contents/apps/desktop/product-identity.cjs' in endpoint:
            return self.identity
        if '/contents/scripts/bundles/desktop.py' in endpoint:
            return self.builder
        if '/git/ref/' in endpoint:
            return {'object': {'type': 'tag', 'sha': 'b' * 40}}
        if '/git/tags/' in endpoint:
            return {'message': json.dumps({'version': '0.22.0', 'commit': self.commit, 'claimTag': 'rc.1-v0.22.0', 'claimTagObject': 'c' * 40})}
        raise AssertionError(endpoint)

    def test_supported_stable_builds_after_capability_and_claim_checks(self):
        self.run_plan(self.response)
        self.result.assert_called_once_with(build='true', ref='v0.22.0', version='0.22.0-r1', claim='rc.1-v0.22.0', claim_object='c' * 40)
        identity = next(i for i, call in enumerate(self.calls) if '/contents/apps/desktop/product-identity.cjs' in call)
        claim = next(i for i, call in enumerate(self.calls) if '/git/ref/' in call)
        self.assertLess(identity, claim)

    def test_non_light_stable_skips_before_release_claim_lookup(self):
        self.identity = {'content': 'ZnVsbCBvbmx5'}  # synthetic full-only source fixture
        self.run_plan(self.response)
        self.result.assert_called_once_with(build='false')
        self.assertFalse(any('/git/' in call for call in self.calls))

    def test_explicit_revision_preserves_upstream_claim(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, BUILD_REVISION='2'):
            self.run_plan(self.response)
        self.result.assert_called_once_with(build='true', ref='v0.22.0', version='0.22.0-r2', claim='rc.1-v0.22.0', claim_object='c' * 40)

    def test_scheduled_r1_does_not_rebuild_or_downgrade_r2(self):
        import json
        import os
        import tempfile
        from unittest.mock import patch
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as scratch:
            try:
                os.chdir(scratch)
                Path('bucket').mkdir()
                target = Path('bucket/hermes-desktop-light.json')
                target.write_text(json.dumps({'version': '0.22.0-r2'}))
                with patch.dict(os.environ, BUILD_REVISION='1'):
                    self.run_plan(self.response)
                self.result.assert_called_once_with(build='false')
                self.assertFalse(any('/commits/' in call for call in self.calls))
                self.result.reset_mock()
                with patch.dict(os.environ, BUILD_REVISION='3'):
                    self.run_plan(self.response)
                self.assertEqual(self.result.call_args.kwargs['version'], '0.22.0-r3')
            finally:
                os.chdir(previous)

    def test_missing_capability_file_skips_but_api_failure_does_not(self):
        import subprocess
        for message in ('gh: Not Found (HTTP 404)', 'gh: API rate limit exceeded (HTTP 403)'):
            with self.subTest(message=message):
                self.result.reset_mock()
                def response(endpoint):
                    if '/contents/' in endpoint:
                        raise subprocess.CalledProcessError(1, ['gh', 'api'], stderr=message)
                    return self.response(endpoint)
                if '404' in message:
                    self.run_plan(response)
                    self.result.assert_called_once_with(build='false')
                else:
                    with self.assertRaises(subprocess.CalledProcessError):
                        self.run_plan(response)
                    self.result.assert_not_called()

    def test_builder_without_light_contract_skips(self):
        import base64
        self.builder = {'content': base64.b64encode(b'parser.add_argument("--tag")').decode()}
        self.run_plan(self.response)
        self.result.assert_called_once_with(build='false')

    def test_preview_checks_pinned_commit_capability(self):
        self.run_plan(self.response, preview=True)
        self.result.assert_called_once_with(build='true', ref=self.light.PREVIEW_SHA, version='preview', claim='', claim_object='')
        self.assertTrue(all('ref=' + self.light.PREVIEW_SHA in call for call in self.calls))
        self.result.reset_mock()
        self.identity = {'content': 'ZnVsbCBvbmx5'}
        self.run_plan(self.response, preview=True)
        self.result.assert_called_once_with(build='false')


if __name__ == '__main__':
    unittest.main()
