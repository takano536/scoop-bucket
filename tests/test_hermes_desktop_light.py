import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/hermes-desktop-light.py'


class ReleaseTests(unittest.TestCase):
    def test_commit_identity_requires_exact_lowercase_sha(self):
        spec = importlib.util.spec_from_file_location('light', SCRIPT)
        assert spec is not None and spec.loader is not None
        light = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(light)
        self.assertEqual(light._commit('a' * 40), 'a' * 40)
        for value in ('a' * 39, 'a' * 41, 'A' * 40, 'g' * 40):
            with self.assertRaisesRegex(ValueError, 'Invalid upstream commit identity'):
                light._commit(value)
    def test_only_published_stable_semver_is_admitted(self):
        self.assertTrue(SCRIPT.exists(), 'Desktop Light release helper is missing')
        spec = importlib.util.spec_from_file_location('light', SCRIPT)
        assert spec is not None and spec.loader is not None
        light = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(light)
        self.assertEqual(light.stable_version({'tag_name': 'v0.22.0', 'draft': False, 'prerelease': False}), '0.22.0')
        for tag in ('v0.22.0-rc.1', 'v0.22.0+canary.20261007T000000Z', 'main', 'v00.22.0'):
            self.assertIsNone(light.stable_version({'tag_name': tag, 'draft': False, 'prerelease': False}))
        self.assertEqual(light.stable_version({'tag_name': 'v2026.9.24', 'draft': False, 'prerelease': False}), '2026.9.24')
        self.assertEqual(light.stable_version({'tag_name': 'v2026.10.1', 'draft': False, 'prerelease': False}), '2026.10.1')
        self.assertIsNone(light.stable_version({'tag_name': 'v0.22.0', 'draft': False, 'prerelease': True}))
        self.assertIsNone(light.stable_version({'tag_name': 'v0.22.0', 'draft': True, 'prerelease': False}))



    def test_development_license_gate_hashes_exact_commit(self):
        import base64
        import hashlib
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location('light', SCRIPT)
        assert spec is not None and spec.loader is not None
        light = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(light)
        commit = 'a' * 40
        content = b'MIT License\nCopyright fixture\n'
        response = {
            'license': {'spdx_id': 'MIT'},
            'content': base64.b64encode(content).decode(),
        }
        with patch.object(light, 'api', return_value=response) as api:
            self.assertEqual(light.license_sha(commit), hashlib.sha256(content).hexdigest())
            api.assert_called_once_with(f'repos/{light.UPSTREAM}/license?ref={commit}')
        with patch.object(light, 'api', return_value={**response, 'license': {'spdx_id': 'Apache-2.0'}}):
            with self.assertRaisesRegex(ValueError, 'MIT licensed'):
                light.license_sha(commit)

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

    def test_development_manifest_binds_full_commit_and_pointer(self):
        spec = importlib.util.spec_from_file_location('light', SCRIPT)
        assert spec is not None and spec.loader is not None
        light = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(light)
        version = '0.0.0-alpha.dev.9-r10'
        commit = 'a' * 40
        result = light.dev_manifest(version, 'takano536/scoop-bucket', 'b' * 64, commit, 'c' * 64)
        self.assertIn('DEVELOPMENT BUILD', result['description'])
        self.assertIn('NOT STABLE', result['notes'])
        self.assertEqual(
            result['architecture']['64bit']['url'],
            f'https://github.com/takano536/scoop-bucket/releases/download/hermes-desktop-light%2Fdev%2Fv{version}-{commit}/hermes-desktop-light-dev-{version}-{commit}-windows-x64.zip',
        )
        self.assertIn('(?<shortsha>', result['checkver']['regex'])
        self.assertEqual(result['autoupdate']['architecture']['64bit']['hash'], {
            'url': 'https://raw.githubusercontent.com/takano536/scoop-bucket/main/metadata/hermes-desktop-light-dev.json',
            'jsonpath': '$.sha256',
        })
        self.assertIn('$matchShortsha', result['autoupdate']['shortcuts'][0][0])
        self.assertEqual(result['shortcuts'][0][0], 'hermes-light-aaaaaaa.exe')

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
        for invalid in ('a' * 39, 'a' * 41, 'A' * 40):
            with self.assertRaisesRegex(ValueError, 'Invalid upstream commit identity'):
                light.release_claim(record, '0.22.0', invalid)


    def test_receipt_rejects_preview_and_tampered_artifact(self):
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
            # Synthetic packaging fixture, never published or reported as a build.
            with zipfile.ZipFile(artifact, 'w') as archive:
                archive.writestr('Hermes Light.exe', b'test fixture')
                archive.writestr('resources/app.asar', b'test fixture')
                archive.writestr('resources/install-stamp.json', '{"payload":"light","updateMechanism":"external","commit":"' + 'a' * 40 + '"}')
            record = dict(schema=1, upstream='NousResearch/hermes-agent', sourceRef='v0.22.0', version='0.22.0-r1', commit='a' * 40, preview=False, artifact=artifact.name, sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(), payload='light', updateMechanism='external', executable='Hermes Light.exe', smoke='two native launches; renderer loaded; localStorage retained')
            self.assertEqual(light.verify_artifact(root, record, '0.22.0-r1', 'v0.22.0'), artifact)
            for change in ({'preview': True}, {'sha256': 'b' * 64}, {'version': '0.21.0'}, {'commit': 'b' * 40}, {'artifact': '../escape.zip'}, {'smoke': 'not run'}):
                with self.assertRaises(ValueError):
                    light.verify_artifact(root, {**record, **change}, '0.22.0-r1', 'v0.22.0')


    def test_development_receipt_requires_exact_commit_and_conditions(self):
        import hashlib
        import json
        import tempfile
        import zipfile
        spec = importlib.util.spec_from_file_location('light', SCRIPT)
        assert spec is not None and spec.loader is not None
        light = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(light)
        version = '0.0.0-alpha.dev.1-r1'
        commit = 'a' * 40
        conditions = 'b' * 64
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            artifact = root / light.dev_artifact_name(light.APP, version, commit)
            with zipfile.ZipFile(artifact, 'w') as archive:
                archive.writestr(f'hermes-light-{commit[:7]}.exe', b'test fixture')
                archive.writestr('resources/app.asar', b'test fixture')
                archive.writestr('resources/install-stamp.json', json.dumps({
                    'payload': 'light', 'updateMechanism': 'external', 'commit': commit,
                }))
            record = dict(
                schema=1, upstream=light.UPSTREAM, sourceRef=commit, commit=commit,
                version=version, preview=False, development=True, channel='development',
                artifact=artifact.name, executable=f'hermes-light-{commit[:7]}.exe',
                payload='light', updateMechanism='external',
                smoke='two native launches; renderer loaded; localStorage retained',
                conditionsFingerprint=conditions,
                sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                light.verify_artifact(root, record, version, commit, 'development', conditions),
                artifact,
            )
            with self.assertRaisesRegex(ValueError, 'conditions fingerprint'):
                light.verify_artifact(root, record, version, commit, 'development', 'c' * 64)
class PlanTests(unittest.TestCase):
    def setUp(self):
        import base64
        from unittest.mock import Mock
        spec = importlib.util.spec_from_file_location('light_plan', SCRIPT)
        assert spec is not None and spec.loader is not None
        self.light = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.light)
        self.commit = 'a' * 40
        self.identity = {'content': base64.b64encode(b"light: { kebab: 'hermes-light' }\nHERMES_BUILD_COMMIT\nwindowsExecutableName").decode()}
        self.builder = {'content': base64.b64encode(b'parser.add_argument("--commit"); parser.add_argument("--variant", choices=["bundled", "store", "light"]); parser.add_argument("builder_args", nargs=argparse.REMAINDER); build_prepared').decode()}
        self.calls = []
        self.result = Mock()

    def run_plan(self, response):
        from unittest.mock import patch
        import os
        def api(endpoint):
            self.calls.append(endpoint)
            return response(endpoint)
        values = {'CHANNEL': 'stable', 'GITHUB_EVENT_NAME': 'workflow_dispatch'}
        with patch.dict(os.environ, values), patch.object(self.light, 'api', side_effect=api), patch.object(self.light, 'output', self.result):
            self.light.plan()

    def run_schedule(self, response, stable_enabled='true'):
        from unittest.mock import patch
        import os
        def api(endpoint):
            self.calls.append(endpoint)
            return response(endpoint)
        values = {
            'GITHUB_EVENT_NAME': 'schedule',
            'CHANNEL': 'development',
            'STABLE_RELEASE_ENABLED': stable_enabled,
            'DEV_RELEASE_ENABLED': '',
            'BUILD_REVISION': '1',
            'REVISION_EXPLICIT': 'false',
        }
        with patch.dict(os.environ, values), patch.object(self.light, 'api', side_effect=api), patch.object(self.light, 'output', self.result):
            self.light.plan()

    def run_dev_plan(self, rows=(), revision='1', explicit='false', pointer=None, event='workflow_dispatch', dev_enabled='true'):
        import json
        import os
        import tempfile
        from unittest.mock import patch
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as scratch:
            try:
                os.chdir(scratch)
                if pointer is not None:
                    Path('metadata').mkdir()
                    Path('metadata/hermes-desktop-light-dev.json').write_text(json.dumps(pointer))
                values = {
                    'CHANNEL': 'development',
                    'GITHUB_EVENT_NAME': event,
                    'GITHUB_REPOSITORY': 'fixture/bucket',
                    'BUILD_REVISION': revision,
                    'REVISION_EXPLICIT': explicit,
                    'DEV_RELEASE_ENABLED': dev_enabled,
                }
                with patch.dict(os.environ, values), \
                     patch.object(self.light, 'main_commit', return_value=self.commit), \
                     patch.object(self.light, 'supports_light', return_value=True), \
                     patch.object(self.light, 'license_sha', return_value='e' * 64), \
                     patch.object(self.light, '_release_rows', return_value=list(rows)) as releases, \
                     patch.object(self.light, 'conditions_fingerprint', return_value='d' * 64), \
                     patch.object(self.light, 'output', self.result):
                    self.light.plan()
                    return releases
            finally:
                os.chdir(previous)

    def test_development_plan_pins_main_and_derives_sequence_from_releases(self):
        old_commit = 'b' * 40
        rows = [{'tag_name': f'hermes-desktop-light/dev/v0.0.0-alpha.dev.9-r1-{old_commit}',
                 'draft': False, 'prerelease': True}]
        self.run_dev_plan(rows=rows)
        self.result.assert_called_once_with(
            build='true',
            channel='development',
            ref=self.commit,
            version='0.0.0-alpha.dev.10-r1',
            release_tag=f'hermes-desktop-light/dev/v0.0.0-alpha.dev.10-r1-{self.commit}',
            artifact=f'hermes-desktop-light-dev-0.0.0-alpha.dev.10-r1-{self.commit}-windows-x64.zip',
            short_sha='a' * 7,
            dev_seq=10,
            revision=1,
            license_sha='e' * 64,
            conditions_fingerprint='d' * 64,
        )

    def test_development_plan_same_conditions_is_idempotent(self):
        pointer = {
            'version': '0.0.0-alpha.dev.1-r1',
            'commit': self.commit,
            'conditionsFingerprint': 'd' * 64,
        }
        self.run_dev_plan(pointer=pointer)
        self.result.assert_called_once_with(build='false', channel='development')

    def test_development_revision_two_requires_dispatch(self):
        with self.assertRaisesRegex(ValueError, 'workflow_dispatch'):
            self.run_dev_plan(revision='2')

    def test_development_plan_ends_after_published_stable_release(self):
        rows = [{'tag_name': 'hermes-desktop-light/v2026.9.24-r1',
                 'draft': False, 'prerelease': False}]
        self.run_dev_plan(rows=rows)
        self.result.assert_called_once_with(build='false', channel='development', transition='stable')
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
        self.result.assert_called_once_with(build='true', ref=self.commit, upstream_tag='v0.22.0', version='0.22.0-r1', claim='rc.1-v0.22.0', claim_object='c' * 40, channel='stable')
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
        self.result.assert_called_once_with(build='true', ref=self.commit, upstream_tag='v0.22.0', version='0.22.0-r2', claim='rc.1-v0.22.0', claim_object='c' * 40, channel='stable')

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


    def test_schedule_selects_stable_only_after_admission_and_gate(self):
        self.run_schedule(self.response)
        self.result.assert_called_once_with(
            build='true', ref=self.commit, upstream_tag='v0.22.0', version='0.22.0-r1',
            claim='rc.1-v0.22.0', claim_object='c' * 40, channel='stable',
        )

    def test_pull_request_development_pins_main_without_bucket_release_listing(self):
        releases = self.run_dev_plan(event='pull_request')
        self.result.assert_called_once_with(
            build='true',
            channel='development',
            ref=self.commit,
            version='0.0.0-alpha.dev.1-r1',
            release_tag=f'hermes-desktop-light/dev/v0.0.0-alpha.dev.1-r1-{self.commit}',
            artifact=f'hermes-desktop-light-dev-0.0.0-alpha.dev.1-r1-{self.commit}-windows-x64.zip',
            short_sha='a' * 7,
            dev_seq=1,
            revision=1,
            license_sha='e' * 64,
            conditions_fingerprint='d' * 64,
        )
        releases.assert_not_called()

    def test_scheduled_development_without_gate_skips_before_build(self):
        self.run_dev_plan(event='schedule', dev_enabled='')
        self.result.assert_called_once_with(build='false', channel='development')
        self.assertEqual(self.result.call_count, 1)


if __name__ == '__main__':
    unittest.main()
