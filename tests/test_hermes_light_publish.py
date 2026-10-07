"""Publisher integration tests: real disposable Git, synthetic ZIP, mocked GitHub."""
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('light_publish', ROOT / 'scripts/hermes-light.py')
assert spec is not None and spec.loader is not None
light = importlib.util.module_from_spec(spec)
spec.loader.exec_module(light)


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.remote = self.root / 'origin.git'
        self.work = self.root / 'work'
        self.work.mkdir()
        self.git('init', '--bare', str(self.remote))
        self.git('init', '-b', 'main', str(self.work))
        self.git('config', 'user.name', 'test fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('remote', 'add', 'origin', str(self.remote))
        (self.work / 'bucket').mkdir()
        (self.work / 'bucket/fixture.json').write_text(json.dumps({
            'version': '1.0.0', 'description': 'Synthetic test fixture',
            'homepage': 'https://example.invalid/fixture',
        }))
        (self.work / 'scripts').mkdir()
        shutil.copyfile(ROOT / 'scripts/update-readme.py', self.work / 'scripts/update-readme.py')
        (self.work / 'README.md').write_text('# Fixture\n\n<!-- BEGIN GENERATED APPS -->\n\n<!-- END GENERATED APPS -->\n')
        self.git('add', 'README.md', 'scripts/update-readme.py', 'bucket/fixture.json')
        self.git('commit', '-m', 'test fixture')
        self.git('push', 'origin', 'main')
        self.initial = self.git('rev-parse', 'HEAD').strip()
        self.output = self.work / 'output'
        self.output.mkdir()
        self.name = 'hermes-agent-light-0.22.0-r1-windows-x64.zip'
        # These bytes are test fixtures, not an application or CI build evidence.
        self.published = self.package('previously published fixture')
        self.record = dict(schema=1, upstream=light.UPSTREAM, version='0.22.0-r1', sourceRef='v0.22.0',
                           preview=False, payload='light', updateMechanism='external', commit='a' * 40,
                           artifact=self.name, executable='Hermes Light.exe',
                           smoke='two native launches; renderer loaded; localStorage retained',
                           notices=self.notice_record(),
                           sha256=hashlib.sha256(self.published).hexdigest())
        rebuilt = self.package('different rebuilt fixture')
        (self.output / self.name).write_bytes(rebuilt)
        (self.output / 'provenance.json').write_text(json.dumps({**self.record, 'sha256': hashlib.sha256(rebuilt).hexdigest()}))
        self.previous_cwd = Path.cwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, self.previous_cwd)
        self.env = patch.dict(os.environ, PACKAGE_VERSION='0.22.0-r1', SOURCE_REF='v0.22.0',
                              GITHUB_REPOSITORY='fixture/bucket', RELEASE_ENABLED='true',
                              GITHUB_ACTIONS='true', GITHUB_REF='refs/heads/main',
                              GITHUB_EVENT_NAME='schedule')
        self.env.start()
        self.addCleanup(self.env.stop)

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.work, text=True, stderr=subprocess.STDOUT)

    def notice_files(self):
        return {
            'LICENSE': 'MIT License\n\nCopyright (c) 2025 Nous Research\n',
            'LICENSE.electron.txt': 'Electron license fixture',
            'LICENSES.chromium.html': '<html>Chromium license fixture</html>',
            'THIRD-PARTY-NOTICES.txt': 'Package fixture: MIT\n',
            'UNOFFICIAL-BUILD.txt': 'Unofficial unsigned build fixture\n',
        }

    def notice_record(self):
        files = self.notice_files()
        return {
            'upstreamLicense': {'path': 'LICENSE', 'sha256': hashlib.sha256(files['LICENSE'].encode()).hexdigest()},
            'thirdParty': {
                'path': 'THIRD-PARTY-NOTICES.txt',
                'sha256': hashlib.sha256(files['THIRD-PARTY-NOTICES.txt'].encode()).hexdigest(),
                'packages': 1,
            },
            'unofficial': {'path': 'UNOFFICIAL-BUILD.txt', 'sha256': hashlib.sha256(files['UNOFFICIAL-BUILD.txt'].encode()).hexdigest()},
        }

    def package(self, marker):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('Hermes Light.exe', marker)
            archive.writestr('resources/app.asar', 'synthetic fixture')
            archive.writestr('resources/install-stamp.json', json.dumps(dict(commit='a' * 40, payload='light', updateMechanism='external')))
            for name, content in self.notice_files().items():
                archive.writestr(name, content)
        return data.getvalue()

    def api(self, endpoint):
        if endpoint == f'repos/{light.UPSTREAM}/commits/v0.22.0':
            return {'sha': 'a' * 40}
        if endpoint == 'repos/fixture/bucket/releases/tags/hermes-agent-light%2Fv0.22.0-r1':
            return {'draft': False, 'prerelease': False}
        if endpoint == 'repos/fixture/bucket/contents/bucket/hermes-agent-light.json?ref=main':
            actual = self.git('show', 'origin/main:bucket/hermes-agent-light.json')
            return {'content': base64.b64encode(actual.encode()).decode()}
        if endpoint == 'repos/fixture/bucket/contents/README.md?ref=main':
            actual = self.git('show', 'origin/main:README.md')
            return {'content': base64.b64encode(actual.encode()).decode()}
        raise AssertionError(f'Unexpected API request: {endpoint}')

    def gh(self, *args):
        if args == ('api', '--paginate', '--slurp', 'repos/fixture/bucket/releases?per_page=100'):
            return json.dumps([[{'tag_name': 'hermes-agent-light/v0.22.0-r1', 'draft': False}]])
        if args[:2] == ('release', 'download'):
            saved = Path(args[args.index('--dir') + 1])
            saved.mkdir()
            (saved / self.name).write_bytes(self.published)
            (saved / 'provenance.json').write_text(json.dumps(self.record))
            return ''
        raise AssertionError(f'Unexpected GitHub mutation or request: {args}')

    def run_publish(self, public_bytes=None):
        with patch.object(light, 'api', side_effect=self.api), patch.object(light, 'gh', side_effect=self.gh), \
             patch('urllib.request.urlopen', return_value=io.BytesIO(self.published if public_bytes is None else public_bytes)) as download:
            light.publish()
            download.assert_called_once_with(
                'https://github.com/fixture/bucket/releases/download/hermes-agent-light%2Fv0.22.0-r1/' + self.name,
                timeout=120)

    def test_publication_requires_explicit_enablement_and_trusted_actions_main(self):
        for values in ({'RELEASE_ENABLED': ''}, {'GITHUB_ACTIONS': ''},
                       {'GITHUB_REF': 'refs/heads/feature'}, {'GITHUB_EVENT_NAME': 'pull_request'}):
            with self.subTest(values=values), patch.dict(os.environ, values), \
                 patch.object(light, 'api') as api, patch.object(light, 'gh') as gh:
                with self.assertRaisesRegex(ValueError, 'Publication is disabled or not a trusted main run'):
                    light.publish()
                api.assert_not_called()
                gh.assert_not_called()
                self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.initial)

    def test_existing_release_reuses_immutable_bytes_and_writes_manifest_readme(self):
        self.run_publish()
        manifest = json.loads(self.git('show', 'origin/main:bucket/hermes-agent-light.json'))
        self.assertEqual(manifest['architecture']['64bit']['hash'], self.record['sha256'])
        self.assertIn('hermes-agent-light', self.git('show', 'origin/main:README.md'))
        self.assertEqual(self.git('status', '--short', '--untracked-files=no').strip(), '')
        # Repeating publication is a no-op, not a rebuilt upload or duplicate commit.
        before = self.git('rev-parse', 'HEAD')
        shutil.rmtree(self.output / 'published')
        self.run_publish()
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)

    def test_public_url_digest_failure_leaves_manifest_unchanged(self):
        with self.assertRaisesRegex(ValueError, 'Public release URL has wrong digest'):
            self.run_publish(b'wrong public fixture')
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.initial)
        self.assertFalse((self.work / 'bucket/hermes-agent-light.json').exists())
        self.assertEqual(self.git('rev-parse', 'origin/main').strip(), self.initial)

    def test_other_application_releases_are_ignored(self):
        real_gh = self.gh
        def gh(*args):
            if args[:3] == ('api', '--paginate', '--slurp'):
                return json.dumps([[{'tag_name': 'other-app/v99.0.0-r10', 'draft': False}],
                                   [{'tag_name': 'hermes-agent-light/v0.22.0-r1', 'draft': False}]])
            return real_gh(*args)
        with patch.object(light, 'api', side_effect=self.api), patch.object(light, 'gh', side_effect=gh), \
             patch('urllib.request.urlopen', return_value=io.BytesIO(self.published)):
            light.publish()
        result = json.loads(self.git('show', 'origin/main:bucket/hermes-agent-light.json'))
        self.assertEqual(result['version'], '0.22.0-r1')
        self.assertEqual(result['checkver']['url'], 'https://raw.githubusercontent.com/fixture/bucket/main/bucket/hermes-agent-light.json')

    def test_same_upstream_revision_downgrade_is_refused(self):
        target = self.work / 'bucket/hermes-agent-light.json'
        target.write_text(json.dumps(light.manifest('0.22.0-r10', 'fixture/bucket', 'b' * 64)))
        self.git('add', str(target))
        self.git('commit', '-m', 'newer revision fixture')
        self.git('push', 'origin', 'main')
        with self.assertRaisesRegex(ValueError, 'Refusing manifest downgrade'):
            self.run_publish()
        self.assertEqual(json.loads(target.read_text())['version'], '0.22.0-r10')

    def test_readme_writeback_is_read_back_not_only_the_manifest(self):
        real_api = self.api

        def api(endpoint):
            if '/contents/README.md?' in endpoint:
                return {'content': base64.b64encode(b'wrong remote README').decode()}
            return real_api(endpoint)

        with patch.object(light, 'api', side_effect=api), patch.object(light, 'gh', side_effect=self.gh), \
             patch('urllib.request.urlopen', return_value=io.BytesIO(self.published)):
            with self.assertRaisesRegex(ValueError, 'README writeback readback mismatch'):
                light.publish()

    def test_new_release_uploads_draft_then_checks_public_url_before_writeback(self):
        mutations = []
        assets = []
        state = {'draft': True, 'prerelease': False, 'assets': assets}
        real_api = self.api

        def api(endpoint):
            if '/releases/tags/' in endpoint:
                return state
            return real_api(endpoint)

        def gh(*args):
            if args[:3] == ('api', '--paginate', '--slurp'):
                return '[[]]'
            mutations.append(args)
            if args[:2] == ('release', 'upload'):
                assets.append({'name': Path(args[3]).name})
            elif args[:2] == ('release', 'edit'):
                state['draft'] = False
            elif args[:2] != ('release', 'create'):
                raise AssertionError(args)
            self.assertFalse((self.work / 'bucket/hermes-agent-light.json').exists())
            return ''

        built = (self.output / self.name).read_bytes()
        with patch.object(light, 'api', side_effect=api), patch.object(light, 'gh', side_effect=gh), \
             patch('urllib.request.urlopen', return_value=io.BytesIO(built)):
            light.publish()
        self.assertEqual([call[1] for call in mutations], ['create', 'upload', 'upload', 'upload', 'edit'])
        historical = json.loads((self.output / 'hermes-agent-light.json').read_text())
        self.assertEqual(historical['version'], '0.22.0-r1')
        self.assertEqual(historical['architecture']['64bit']['hash'], hashlib.sha256(built).hexdigest())
        self.assertIn('--draft', mutations[0])
        self.assertIn('--latest=false', mutations[0])
        self.assertFalse(any('--clobber' in call for call in mutations))
        data = json.loads(self.git('show', 'origin/main:bucket/hermes-agent-light.json'))
        self.assertEqual(data['architecture']['64bit']['hash'], hashlib.sha256(built).hexdigest())

    def test_different_partial_draft_is_not_overwritten_or_published(self):
        real_api = self.api

        def api(endpoint):
            if '/releases/tags/' in endpoint:
                return {'draft': True, 'prerelease': False, 'assets': [{'name': self.name}]}
            return real_api(endpoint)

        def gh(*args):
            if args[:3] == ('api', '--paginate', '--slurp'):
                return json.dumps([[{'tag_name': 'hermes-agent-light/v0.22.0-r1', 'draft': True}]])
            if args[:2] == ('release', 'download'):
                (Path(args[args.index('--dir') + 1]) / self.name).write_bytes(self.published)
                return ''
            raise AssertionError(f'Draft must not be mutated: {args}')

        with patch.object(light, 'api', side_effect=api), patch.object(light, 'gh', side_effect=gh), \
             patch('urllib.request.urlopen') as download:
            with self.assertRaisesRegex(ValueError, 'Existing draft asset differs'):
                light.publish()
            download.assert_not_called()
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.initial)
        self.assertFalse((self.work / 'bucket/hermes-agent-light.json').exists())

    def test_moved_upstream_tag_is_rejected_before_release_mutation(self):
        with patch.object(light, 'api', return_value={'sha': 'b' * 40}), \
             patch.object(light, 'gh') as gh:
            with self.assertRaisesRegex(ValueError, 'Upstream tag moved'):
                light.publish()
            gh.assert_not_called()
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.initial)

    def test_manifest_downgrade_is_refused(self):
        target = self.work / 'bucket/hermes-agent-light.json'
        target.write_text(json.dumps(light.manifest('0.23.0-r1', 'fixture/bucket', 'b' * 64)))
        self.git('add', str(target))
        self.git('commit', '-m', 'newer fixture distribution')
        self.git('push', 'origin', 'main')
        newer = self.git('rev-parse', 'HEAD')
        with self.assertRaisesRegex(ValueError, 'Refusing manifest downgrade'):
            self.run_publish()
        self.assertEqual(self.git('rev-parse', 'origin/main'), newer)
        self.assertEqual(json.loads(target.read_text())['version'], '0.23.0-r1')

    def test_push_failure_preserves_remote_and_published_bytes_for_retry(self):
        real_run = subprocess.run
        pushes = []

        def run(args, **kwargs):
            if args == ['git', 'push', 'origin', 'HEAD:main']:
                pushes.append(args)
                return subprocess.CompletedProcess(args, 1)
            return real_run(args, **kwargs)

        with patch.object(light.subprocess, 'run', side_effect=run):
            with self.assertRaisesRegex(RuntimeError, 'published artifact is retained for retry'):
                self.run_publish()
        self.assertEqual(len(pushes), 3)
        self.assertEqual(self.git('rev-parse', 'origin/main').strip(), self.initial)
        self.assertEqual((self.output / 'published' / self.name).read_bytes(), self.published)


if __name__ == '__main__':
    unittest.main()
