import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/hermes-light.py'


class ReleaseTests(unittest.TestCase):
    def test_only_published_stable_semver_is_admitted(self):
        self.assertTrue(SCRIPT.exists(), 'Light release helper is missing')
        spec = importlib.util.spec_from_file_location('light', SCRIPT)
        assert spec is not None and spec.loader is not None
        light = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(light)
        self.assertEqual(light.stable_version({'tag_name': 'v0.22.0', 'draft': False, 'prerelease': False}), '0.22.0')
        for tag in ('v2026.9.24', 'v0.22.0-rc.1', 'v0.22.0+canary.20261007T000000Z', 'main', 'v00.22.0'):
            self.assertIsNone(light.stable_version({'tag_name': tag, 'draft': False, 'prerelease': False}))
        self.assertIsNone(light.stable_version({'tag_name': 'v0.22.0', 'draft': False, 'prerelease': True}))
        self.assertIsNone(light.stable_version({'tag_name': 'v0.22.0', 'draft': True, 'prerelease': False}))


    def test_manifest_binds_version_repository_and_exact_bytes(self):
        spec = importlib.util.spec_from_file_location('light', SCRIPT)
        assert spec is not None and spec.loader is not None
        light = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(light)
        self.assertTrue(hasattr(light, 'manifest'), 'Manifest generation is missing')
        result = light.manifest('0.22.0', 'takano536/scoop-bucket', 'a' * 64)
        self.assertEqual(result['version'], '0.22.0')
        self.assertEqual(result['architecture']['64bit']['hash'], 'a' * 64)
        self.assertEqual(result['architecture']['64bit']['url'], 'https://github.com/takano536/scoop-bucket/releases/download/hermes-agent-light-v0.22.0/hermes-agent-light-0.22.0-windows-x64.zip')
        self.assertEqual(result['autoupdate']['architecture']['64bit']['url'], 'https://github.com/takano536/scoop-bucket/releases/download/hermes-agent-light-v$version/hermes-agent-light-$version-windows-x64.zip')
        self.assertEqual(result['shortcuts'][0][0], 'Hermes Light.exe')
        for version, repository, digest in [('0.22.0-rc.1', 'a/b', 'a' * 64), ('0.22.0', 'bad', 'a' * 64), ('0.22.0', 'a/b', 'bad')]:
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
            artifact = root / 'hermes-agent-light-0.22.0-windows-x64.zip'
            # Synthetic packaging fixture, never published or reported as a build.
            with zipfile.ZipFile(artifact, 'w') as archive:
                archive.writestr('Hermes Light.exe', b'test fixture')
                archive.writestr('resources/app.asar', b'test fixture')
                archive.writestr('resources/install-stamp.json', '{"payload":"light","updateMechanism":"external","commit":"' + 'a' * 40 + '"}')
            record = dict(schema=1, upstream='NousResearch/hermes-agent', sourceRef='v0.22.0', version='0.22.0', commit='a' * 40, preview=False, artifact=artifact.name, sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(), payload='light', updateMechanism='external', executable='Hermes Light.exe', smoke='two native launches; renderer loaded; localStorage retained')
            self.assertEqual(light.verify_artifact(root, record, '0.22.0', 'v0.22.0'), artifact)
            for change in ({'preview': True}, {'sha256': 'b' * 64}, {'version': '0.21.0'}, {'commit': 'b' * 40}, {'artifact': '../escape.zip'}, {'smoke': 'not run'}):
                with self.assertRaises(ValueError):
                    light.verify_artifact(root, {**record, **change}, '0.22.0', 'v0.22.0')


if __name__ == '__main__':
    unittest.main()
