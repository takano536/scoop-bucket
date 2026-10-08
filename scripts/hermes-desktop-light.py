#!/usr/bin/env python3
"""Stable and development admission, provenance, and Scoop metadata."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distribution import (dev_artifact_name, dev_package_version, dev_release_tag,
                          dev_version_key, distribution_version_key, package_version,
                          release_tag, version_key)

UPSTREAM = 'NousResearch/hermes-agent'
APP = 'hermes-desktop-light'
VERSION = re.compile(r'v(0|[1-9]\d{0,2})\.(0|[1-9]\d*)\.(0|[1-9]\d*)')
DEV_TAG = re.compile(
    rf'^{re.escape(APP)}/dev/v0\.0\.0-alpha\.dev\.([1-9]\d*)-r([1-9]\d*)-([a-f0-9]{{40}})$')
STABLE_TAG = re.compile(rf'^{re.escape(APP)}/v(.+)$')
DEV_POINTER = Path('metadata/hermes-desktop-light-dev.json')
CHANNEL_RECORD = Path('metadata/hermes-desktop-light-channel.json')


def stable_version(release):
    tag = release.get('tag_name', '')
    if release.get('draft') is not False or release.get('prerelease') is not False:
        return None
    return tag[1:] if VERSION.fullmatch(tag) else None


def _repository(repository):
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', repository):
        raise ValueError('Invalid repository identity')
    return repository


def _digest(value):
    if not re.fullmatch(r'[a-f0-9]{64}', value):
        raise ValueError('Invalid artifact digest')
    return value


def _commit(value):
    if not re.fullmatch(r'[a-f0-9]{40}', value):
        raise ValueError('Invalid upstream commit identity')
    return value


def _download_url(repository, tag, name):
    return f'https://github.com/{_repository(repository)}/releases/download/{quote(tag, safe="")}/{name}'


def manifest(version, repository, digest):
    """Stable manifest; keep this path compatible with the stable publisher."""
    version_key(version)
    digest = _digest(digest)
    name = f'{APP}-{version}-windows-x64.zip'
    tag = release_tag(APP, version)
    return {
        'version': version,
        'description': 'Hermes Desktop Light remote-only desktop client (Light)',
        'homepage': 'https://github.com/NousResearch/hermes-agent',
        'license': 'MIT',
        'architecture': {'64bit': {
            'url': _download_url(repository, tag, name),
            'hash': digest,
        }},
        'shortcuts': [['Hermes Light.exe', 'Hermes Desktop Light']],
        'checkver': {
            'url': f'https://raw.githubusercontent.com/{_repository(repository)}/main/bucket/{APP}.json',
            'regex': r'"version"\s*:\s*"(\d+\.\d+\.\d+-r[1-9]\d*)"',
        },
        'autoupdate': {'architecture': {'64bit': {
            'url': f'https://github.com/{_repository(repository)}/releases/download/{APP}%2Fv$version/{APP}-$version-windows-x64.zip',
        }}},
        'notes': 'Unofficial unsigned x64 build. Connect to an existing Hermes gateway; no local Python or agent is bundled. Settings remain in the application user-data directory outside Scoop.',
    }


def dev_manifest(version, repository, digest, commit, conditions_fingerprint):
    """Development manifest whose URL is bound to a full upstream SHA."""
    dev_version_key(version)
    commit = _commit(commit)
    digest = _digest(digest)
    if not re.fullmatch(r'[a-f0-9]{64}', conditions_fingerprint):
        raise ValueError('Invalid conditions fingerprint')
    short_sha = commit[:7]
    name = dev_artifact_name(APP, version, commit)
    tag = dev_release_tag(APP, version, commit)
    pointer = f'https://raw.githubusercontent.com/{_repository(repository)}/main/{DEV_POINTER.as_posix()}'
    return {
        'version': version,
        'description': 'Hermes Desktop Light DEVELOPMENT BUILD — NOT STABLE from upstream main',
        'homepage': 'https://github.com/NousResearch/hermes-agent',
        'license': 'MIT',
        'architecture': {'64bit': {
            'url': _download_url(repository, tag, name),
            'hash': digest,
        }},
        'shortcuts': [[f'hermes-light-{short_sha}.exe', 'Hermes Desktop Light (Development)']],
        'checkver': {
            'url': pointer,
            'regex': r'"version"\s*:\s*"(?<version>0\.0\.0-alpha\.dev\.[1-9]\d*-r[1-9]\d*)"[\s\S]*?"commit"\s*:\s*"(?<commit>[a-f0-9]{40})"[\s\S]*?"shortSha"\s*:\s*"(?<shortsha>[a-f0-9]{7})"',
        },
        'autoupdate': {
            'architecture': {'64bit': {
                'url': f'https://github.com/{_repository(repository)}/releases/download/{APP}%2Fdev%2Fv$matchVersion-$matchCommit/{APP}-dev-$matchVersion-$matchCommit-windows-x64.zip',
                'hash': {'url': pointer, 'jsonpath': '$.sha256'},
            }},
            'shortcuts': [[f'hermes-light-$matchShortsha.exe', 'Hermes Desktop Light (Development)']],
        },
        'notes': 'DEVELOPMENT BUILD — NOT STABLE. Unofficial unsigned x64 build from the pinned upstream main commit; connect to an existing Hermes gateway. No local Python or agent is bundled.',
    }


def dev_pointer(version, repository, digest, commit, conditions_fingerprint, license_sha256):
    dev_version_key(version)
    commit = _commit(commit)
    digest = _digest(digest)
    if not re.fullmatch(r'[a-f0-9]{64}', conditions_fingerprint):
        raise ValueError('Invalid conditions fingerprint')
    if not re.fullmatch(r'[a-f0-9]{64}', license_sha256):
        raise ValueError('Invalid license fingerprint')
    return {
        'schema': 1,
        'channel': 'development',
        'development': True,
        'version': version,
        'commit': commit,
        'shortSha': commit[:7],
        'releaseTag': dev_release_tag(APP, version, commit),
        'artifact': dev_artifact_name(APP, version, commit),
        'sha256': digest,
        'licenseSha256': license_sha256,
        'conditionsFingerprint': conditions_fingerprint,
    }


def release_claim(record, version, commit):
    claim = record.get('claimTag', '')
    obj = record.get('claimTagObject', '')
    if record.get('version') != version or record.get('commit') != commit or not re.fullmatch(r'rc\.[1-9]\d*-v' + re.escape(version), claim) or not re.fullmatch(r'[a-f0-9]{40}', obj):
        raise ValueError('Release has no valid immutable build claim')
    return claim, obj


def gh(*args):
    return subprocess.check_output(['gh', *args], text=True, encoding='utf-8', stderr=subprocess.PIPE)


def api(endpoint):
    return json.loads(gh('api', endpoint))


def output(**values):
    for key, value in values.items():
        print(f'{key}={value}')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            for key, value in values.items():
                stream.write(f'{key}={value}\n')


def supports_light(commit):
    """Preflight exact source without executing it; only missing files mean skip."""
    sources = {}
    for path in ('apps/desktop/product-identity.cjs', 'scripts/bundles/desktop.py'):
        try:
            record = api(f'repos/{UPSTREAM}/contents/{path}?ref={commit}')
        except subprocess.CalledProcessError as exc:
            if '(HTTP 404)' not in (exc.stderr or ''):
                raise
            print(f'Skipping {commit}: no {path}')
            return False
        sources[path] = base64.b64decode(record['content']).decode('utf-8')
    builder = sources['scripts/bundles/desktop.py']
    supported = ('hermes-light' in sources['apps/desktop/product-identity.cjs'] and
                 '--variant' in builder and
                 ('"light"' in builder or "'light'" in builder))
    if not supported:
        print(f'Skipping {commit}: source lacks the managed Light build contract')
    return supported


def license_sha(commit):
    """Require MIT at the exact admitted commit and return its content hash."""
    record = api(f'repos/{UPSTREAM}/license?ref={commit}')
    if record.get('license', {}).get('spdx_id') != 'MIT':
        raise ValueError('Upstream exact commit is not MIT licensed')
    try:
        content = base64.b64decode(record['content'])
    except (KeyError, ValueError) as exc:
        raise ValueError('Upstream exact commit has no readable LICENSE') from exc
    if not content.lstrip().startswith(b'MIT License'):
        raise ValueError('Upstream exact commit LICENSE is not MIT')
    return hashlib.sha256(content).hexdigest()


def main_commit():
    record = api(f'repos/{UPSTREAM}/git/ref/heads/main')
    obj = record.get('object', {})
    if record.get('ref') != 'refs/heads/main' or obj.get('type') != 'commit' or not re.fullmatch(r'[a-f0-9]{40}', obj.get('sha', '')):
        raise ValueError('Upstream main did not resolve to an immutable commit')
    return obj['sha']


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')


def conditions_descriptor(commit):
    """Hash stable, non-ephemeral inputs which affect a development build."""
    root = Path(__file__).resolve().parents[1]
    files = {}
    for relative in (
        'scripts/hermes-desktop-light.py',
        'scripts/build-hermes-desktop-light.ps1',
        'scripts/smoke-hermes-desktop-light.cjs',
        'scripts/distribution.py',
        '.github/workflows/hermes-desktop-light.yml',
    ):
        path = root / relative
        if path.is_file():
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    bundle_env = os.environ.get('HERMES_BUNDLE_ENV_JSON', '')
    return {
        'schema': 1,
        'channel': 'development',
        'upstream': UPSTREAM,
        'upstreamRef': 'main',
        'commit': _commit(commit),
        'variant': 'light',
        'target': 'win32-x64',
        'buildMode': 'commit',
        'runner': 'windows-2025',
        'python': '3.13',
        'builderArgs': ['--dir'],
        'compression': 'Compress-Archive:Optimal',
        'signing': 'unsigned',
        'localPayload': False,
        'bundleEnvSha256': hashlib.sha256(bundle_env.encode('utf-8')).hexdigest(),
        'bucketInputs': files,
    }


def conditions_fingerprint(commit):
    return hashlib.sha256(_canonical_json(conditions_descriptor(commit))).hexdigest()


def _release_rows(repository):
    if not repository:
        return []
    pages = json.loads(gh('api', '--paginate', '--slurp', f'repos/{_repository(repository)}/releases?per_page=100'))
    return [row for page in pages for row in page]


def _dev_release(row):
    if row.get('draft', False) or row.get('prerelease') is not True:
        return None
    match = DEV_TAG.fullmatch(row.get('tag_name', ''))
    if not match:
        return None
    sequence, revision, commit = match.groups()
    return int(sequence), int(revision), commit


def _stable_release(row):
    if row.get('draft', False) or row.get('prerelease', False):
        return None
    match = STABLE_TAG.fullmatch(row.get('tag_name', ''))
    if not match:
        return None
    try:
        return version_key(match.group(1))
    except ValueError:
        return None


def _stable_manifest_present():
    target = Path(f'bucket/{APP}.json')
    if not target.exists():
        return False
    try:
        current = json.loads(target.read_text(encoding='utf-8'))['version']
        return distribution_version_key(current)[0] == 1
    except (KeyError, ValueError):
        return False


def _has_stable_release(rows):
    return any(_stable_release(row) is not None for row in rows)


def _read_json(path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _revision(value):
    if not re.fullmatch(r'[1-9]\d*', str(value)):
        raise ValueError('Revision must be a positive integer without leading zeroes')
    return int(value)


def _stable_admission_available():
    """Check the upstream stable admission without mutating bucket state."""
    release = api(f'repos/{UPSTREAM}/releases/latest')
    upstream_version = stable_version(release)
    if upstream_version is None:
        return False
    tag = release['tag_name']
    commit = api(f'repos/{UPSTREAM}/commits/{tag}')['sha']
    if not supports_light(commit):
        return False
    ref = api(f'repos/{UPSTREAM}/git/ref/tags/{tag}')['object']
    if ref['type'] != 'tag':
        raise ValueError('Stable build requires an annotated upstream release tag')
    record = api(f"repos/{UPSTREAM}/git/tags/{ref['sha']}")
    metadata = json.loads(record['message'].split('\n-----BEGIN ', 1)[0])
    release_claim(metadata, upstream_version, commit)
    return True


def _plan_stable():
    release = api(f'repos/{UPSTREAM}/releases/latest')
    version = stable_version(release)
    if version is None:
        print(f"Waiting for a published stable SemVer release with Light support; latest: {release['tag_name']}")
        output(build='false')
        return
    upstream_version = version
    version = package_version(upstream_version, os.environ.get('BUILD_REVISION', '1'))
    current = Path('bucket/hermes-desktop-light.json')
    if current.exists():
        current_version = json.loads(current.read_text(encoding='utf-8'))['version']
        if distribution_version_key(current_version) >= distribution_version_key(version):
            print('Manifest is already current; nothing to build')
            output(build='false')
            return
    tag = release['tag_name']
    commit = api(f'repos/{UPSTREAM}/commits/{tag}')['sha']
    if not supports_light(commit):
        output(build='false')
        return
    ref = api(f'repos/{UPSTREAM}/git/ref/tags/{tag}')['object']
    if ref['type'] != 'tag':
        raise ValueError('Stable build requires an annotated upstream release tag')
    record = api(f"repos/{UPSTREAM}/git/tags/{ref['sha']}")
    metadata = json.loads(record['message'].split('\n-----BEGIN ', 1)[0])
    claim, claim_object = release_claim(metadata, upstream_version, commit)
    output(build='true', ref=tag, version=version, claim=claim, claim_object=claim_object, channel='stable')


def _plan_development():
    event = os.environ.get('GITHUB_EVENT_NAME', '')
    if event == 'schedule' and os.environ.get('DEV_RELEASE_ENABLED') != 'true':
        print('Scheduled development publication is disabled; development gate is not true')
        output(build='false', channel='development')
        return
    commit = main_commit()
    if not supports_light(commit):
        output(build='false', channel='development')
        return
    exact_license_sha = license_sha(commit)
    fingerprint = conditions_fingerprint(commit)
    pull_request = event == 'pull_request'
    repository = '' if pull_request else os.environ.get('GITHUB_REPOSITORY', '')
    rows = [] if pull_request else _release_rows(repository)
    if not pull_request and (_has_stable_release(rows) or CHANNEL_RECORD.exists() or _stable_manifest_present()):
        print('Development tracking has ended: a stable Hermes Desktop Light release exists')
        output(build='false', channel='development', transition='stable')
        return
    pointer = None if pull_request else _read_json(DEV_POINTER)
    requested = _revision(os.environ.get('BUILD_REVISION', '1'))
    explicit = os.environ.get('REVISION_EXPLICIT') == 'true'
    if requested > 1 and not explicit and not pull_request:
        raise ValueError('Development revisions above r1 require workflow_dispatch')

    if pull_request:
        sequence = 1
        requested = 1
    else:
        published = [_dev_release(row) for row in rows]
        published = [item for item in published if item]
        same_commit = [item for item in published if item[2] == commit]
        if pointer and pointer.get('commit') == commit:
            sequence = int(pointer['version'].split('.dev.', 1)[1].split('-r', 1)[0])
            previous_revision = dev_version_key(pointer['version'])[1]
            if pointer.get('conditionsFingerprint') == fingerprint:
                if requested != previous_revision:
                    raise ValueError('Same development build conditions require the existing revision')
                print('Development build is already published for this commit and conditions')
                output(build='false', channel='development')
                return
            if requested <= previous_revision:
                raise ValueError('Development conditions changed; workflow_dispatch with a higher revision is required')
        elif same_commit:
            sequence = max(item[0] for item in same_commit)
            previous_revision = max(item[1] for item in same_commit)
            if requested <= previous_revision:
                requested = previous_revision
            elif not explicit:
                raise ValueError('Development revisions above r1 require workflow_dispatch')
        else:
            sequence = max((item[0] for item in published), default=0) + 1
            if requested != 1:
                raise ValueError('A new upstream commit must start at development r1')
    version = dev_package_version(sequence, requested)
    output(build='true', channel='development', ref=commit, version=version,
           release_tag=dev_release_tag(APP, version, commit),
           artifact=dev_artifact_name(APP, version, commit), short_sha=commit[:7],
           dev_seq=sequence, revision=requested, license_sha=exact_license_sha,
           conditions_fingerprint=fingerprint)


def plan():
    event = os.environ.get('GITHUB_EVENT_NAME', '')
    if event == 'schedule':
        if (os.environ.get('STABLE_RELEASE_ENABLED') == 'true' and
                _stable_admission_available()):
            _plan_stable()
        else:
            _plan_development()
        return
    channel = os.environ.get('CHANNEL', 'stable')
    if event == 'pull_request':
        channel = 'development'
    if channel == 'development':
        _plan_development()
    elif channel == 'stable':
        _plan_stable()
    else:
        raise ValueError(f'Unknown channel: {channel}')


def _verify_common_stamp(archive, record):
    stamp = json.loads(archive.read('resources/install-stamp.json'))
    if any(stamp.get(key) != record[key] for key in ('commit', 'payload', 'updateMechanism')):
        raise ValueError('Packaged provenance mismatch')


def verify_artifact(root, record, version, source_ref, channel='stable', expected_conditions=None):
    import zipfile
    artifact = None
    if channel == 'development' or record.get('development') is True:
        dev_version_key(version)
        commit = _commit(record.get('commit', ''))
        if source_ref != commit or record.get('sourceRef') != source_ref:
            raise ValueError('Development source identity mismatch')
        expected_name = dev_artifact_name(APP, version, commit)
        expected_executable = f'hermes-light-{commit[:7]}.exe'
        expected = {
            'schema': 1, 'upstream': UPSTREAM, 'version': version, 'sourceRef': source_ref,
            'preview': False, 'development': True, 'channel': 'development',
            'payload': 'light', 'updateMechanism': 'external', 'artifact': expected_name,
            'executable': expected_executable,
            'smoke': 'two native launches; renderer loaded; localStorage retained',
        }
        if expected_conditions is not None and record.get('conditionsFingerprint') != expected_conditions:
            raise ValueError('Build conditions fingerprint mismatch')
    else:
        key = version_key(version)
        if source_ref != 'v' + '.'.join(map(str, key[:3])):
            raise ValueError('Distribution version does not match upstream source tag')
        expected_name = f'{APP}-{version}-windows-x64.zip'
        expected_executable = 'Hermes Light.exe'
        expected = {
            'schema': 1, 'upstream': UPSTREAM, 'version': version, 'sourceRef': source_ref,
            'preview': False, 'payload': 'light', 'updateMechanism': 'external',
            'artifact': expected_name, 'executable': expected_executable,
            'smoke': 'two native launches; renderer loaded; localStorage retained',
        }
        if record.get('development') is True:
            raise ValueError('Unverified or development artifact cannot be published as stable')
    if any(record.get(key) != value for key, value in expected.items()):
        raise ValueError('Unverified or preview artifact cannot be published')
    if not re.fullmatch(r'[a-f0-9]{64}', record.get('sha256', '')):
        raise ValueError('Artifact has no valid digest')
    artifact = root / expected_name
    if hashlib.sha256(artifact.read_bytes()).hexdigest() != record.get('sha256'):
        raise ValueError('Artifact digest mismatch')
    with zipfile.ZipFile(artifact) as archive:
        names = archive.namelist()
        if expected_executable not in names or 'resources/app.asar' not in names or any(name.startswith('resources/agent-payload/') for name in names):
            raise ValueError('Invalid Light package contents')
        if archive.testzip() is not None:
            raise ValueError('Corrupt ZIP')
        _verify_common_stamp(archive, record)
    return artifact


def _trusted_publish_gate():
    if (os.environ.get('RELEASE_ENABLED') != 'true' or
            os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('GITHUB_REF') != 'refs/heads/main' or
            os.environ.get('GITHUB_EVENT_NAME') not in ('schedule', 'workflow_dispatch')):
        raise ValueError('Publication is disabled or not a trusted main run')




def _writeback(data, version, channel, repository, pointer=None, transition=None):
    """Write only verified metadata, preserving concurrent main changes."""
    subprocess.run(['git', 'config', 'user.name', 'github-actions[bot]'], check=True)
    subprocess.run(['git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'], check=True)
    for _ in range(3):
        subprocess.run(['git', 'fetch', 'origin', 'main'], check=True)
        subprocess.run(['git', 'reset', '--hard', 'origin/main'], check=True)
        target = Path(f'bucket/{APP}.json')
        previous_channel = None
        if target.exists():
            current_version = json.loads(target.read_text(encoding='utf-8'))['version']
            current_key = distribution_version_key(current_version)
            previous_channel = 'development' if current_key[0] == 0 else 'stable'
            if current_key > distribution_version_key(version):
                raise ValueError('Refusing manifest downgrade')
        target.write_text(json.dumps(data, indent=4) + '\n', encoding='utf-8')
        files = [target]
        if pointer is not None:
            pointer_path = Path(pointer['path'])
            pointer_path.parent.mkdir(parents=True, exist_ok=True)
            pointer_path.write_text(json.dumps(pointer['data'], indent=2) + '\n', encoding='utf-8')
            files.append(pointer_path)
        if transition is not None and previous_channel == 'development':
            marker = Path('metadata/hermes-desktop-light-channel.json')
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps(transition, indent=2) + '\n', encoding='utf-8')
            files.append(marker)
        subprocess.run(['python3', 'scripts/update-readme.py'], check=True)
        subprocess.run(['python3', 'scripts/update-readme.py', '--check'], check=True)
        files.append(Path('README.md'))
        subprocess.run(['git', 'add', *(str(file) for file in files)], check=True)
        if subprocess.run(['git', 'diff', '--cached', '--quiet']).returncode == 0:
            return
        subprocess.run(['git', 'commit', '-m', f'chore: update {APP} to {version}'], check=True)
        if subprocess.run(['git', 'push', 'origin', 'HEAD:main']).returncode == 0:
            remote = api(f'repos/{repository}/contents/bucket/{APP}.json?ref=main')
            actual = json.loads(base64.b64decode(remote['content']))
            if actual != data:
                raise ValueError('Manifest writeback readback mismatch')
            if pointer is not None:
                pointer_remote = api(f"repos/{repository}/contents/{pointer['path']}?ref=main")
                pointer_actual = json.loads(base64.b64decode(pointer_remote['content']))
                if pointer_actual != pointer['data']:
                    raise ValueError('Pointer writeback readback mismatch')
            remote_readme = api(f'repos/{repository}/contents/README.md?ref=main')
            actual_readme = base64.b64decode(remote_readme['content']).decode('utf-8').replace('\r\n', '\n')
            if actual_readme != Path('README.md').read_text(encoding='utf-8'):
                raise ValueError('README writeback readback mismatch')
            return
    raise RuntimeError('Manifest push failed; published artifact is retained for retry')


def _publish_development():
    import tempfile
    import urllib.request
    version, source_ref = os.environ['PACKAGE_VERSION'], os.environ['SOURCE_REF']
    repository = _repository(os.environ['GITHUB_REPOSITORY'])
    fingerprint = os.environ['CONDITIONS_FINGERPRINT']
    license_digest = os.environ['LICENSE_SHA256']
    if not re.fullmatch(r'[a-f0-9]{64}', license_digest):
        raise ValueError('Development publication has no valid exact-commit license digest')
    rows = _release_rows(repository)
    if _has_stable_release(rows) or CHANNEL_RECORD.exists() or _stable_manifest_present():
        raise ValueError('Development publication is closed after the stable transition')
    record = json.loads((Path('output') / 'provenance.json').read_text(encoding='utf-8-sig'))
    if record.get('licenseSha256') != license_digest:
        raise ValueError('Build license digest does not match the admitted commit')
    artifact = verify_artifact(Path('output'), record, version, source_ref, 'development', fingerprint)
    if api(f'repos/{UPSTREAM}/commits/{source_ref}').get('sha') != source_ref:
        raise ValueError('Pinned upstream commit does not exist at the exact SHA')
    if record['commit'] != source_ref:
        raise ValueError('Build provenance is not bound to the pinned upstream commit')
    tag = dev_release_tag(APP, version, record['commit'])
    if os.environ.get('RELEASE_TAG') and os.environ['RELEASE_TAG'] != tag:
        raise ValueError('Development release tag mismatch')
    pages = json.loads(gh('api', '--paginate', '--slurp', f'repos/{repository}/releases?per_page=100'))
    existing = next((row for page in pages for row in page if row['tag_name'] == tag), None)
    if existing and not existing['draft']:
        saved = Path('output/published')
        saved.mkdir(parents=True, exist_ok=True)
        gh('release', 'download', tag, '--repo', repository, '--pattern', artifact.name,
           '--pattern', 'provenance.json', '--dir', str(saved))
        published = json.loads((saved / 'provenance.json').read_text(encoding='utf-8-sig'))
        artifact = verify_artifact(saved, published, version, source_ref, 'development', fingerprint)
        if published['commit'] != source_ref:
            raise ValueError('Existing release belongs to another source')
        record = published
    else:
        if not existing:
            gh('release', 'create', tag, '--repo', repository, '--draft', '--target', 'main',
               '--title', f'Hermes Desktop Light development {version} (not stable)', '--notes',
               f'DEVELOPMENT BUILD — NOT STABLE. Unofficial unsigned Windows x64 Light build from {UPSTREAM}@{source_ref}. '
               f'Pinned main commit; MIT LICENSE SHA256 {license_digest}; conditions fingerprint {fingerprint}. Remote-only; no Python/local agent. '
               'Scoop owns updates. See provenance.json for build and smoke receipts.', '--latest=false')
        state = api(f'repos/{repository}/releases/tags/{quote(tag, safe="")}')
        history_manifest = Path('output') / f'{APP}.json'
        history_manifest.write_text(json.dumps(dev_manifest(version, repository, record['sha256'], record['commit'], fingerprint), indent=4) + '\n', encoding='utf-8')
        for file in (artifact, Path('output/provenance.json'), history_manifest):
            prior = next((asset for asset in state['assets'] if asset['name'] == file.name), None)
            if prior:
                with tempfile.TemporaryDirectory() as scratch:
                    gh('release', 'download', tag, '--repo', repository, '--pattern', file.name, '--dir', scratch)
                    if (Path(scratch) / file.name).read_bytes() != file.read_bytes():
                        raise ValueError('Existing draft asset differs; refusing overwrite')
            else:
                gh('release', 'upload', tag, str(file), '--repo', repository)
        gh('release', 'edit', tag, '--repo', repository, '--draft=false', '--prerelease=true', '--latest=false')
    state = api(f'repos/{repository}/releases/tags/{quote(tag, safe="")}')
    if state['draft'] or not state['prerelease']:
        raise ValueError('Development release publication did not read back as prerelease')
    digest = record['sha256']
    data = dev_manifest(version, repository, digest, record['commit'], fingerprint)
    url = data['architecture']['64bit']['url']
    with urllib.request.urlopen(url, timeout=120) as response:
        hasher = hashlib.sha256()
        while chunk := response.read(1024 * 1024):
            hasher.update(chunk)
    if hasher.hexdigest() != digest:
        raise ValueError('Public release URL has wrong digest; manifest left unchanged')
    pointer = dev_pointer(version, repository, digest, record['commit'], fingerprint, license_digest)
    _writeback(data, version, 'development', repository,
               pointer={'path': DEV_POINTER.as_posix(), 'data': pointer})


def _publish_stable():
    import tempfile
    import urllib.request
    version, source_ref = os.environ['PACKAGE_VERSION'], os.environ['SOURCE_REF']
    repository = _repository(os.environ['GITHUB_REPOSITORY'])
    root = Path('output')
    record = json.loads((root / 'provenance.json').read_text(encoding='utf-8-sig'))
    artifact = verify_artifact(root, record, version, source_ref)
    upstream_commit = api(f'repos/{UPSTREAM}/commits/{source_ref}')['sha']
    if record['commit'] != upstream_commit:
        raise ValueError('Upstream tag moved or build has wrong source')
    tag = release_tag(APP, version)
    pages = json.loads(gh('api', '--paginate', '--slurp', f'repos/{repository}/releases?per_page=100'))
    existing = next((row for page in pages for row in page if row['tag_name'] == tag), None)
    if existing and not existing['draft']:
        saved = root / 'published'
        gh('release', 'download', tag, '--repo', repository, '--pattern', artifact.name,
           '--pattern', 'provenance.json', '--dir', str(saved))
        published = json.loads((saved / 'provenance.json').read_text(encoding='utf-8-sig'))
        artifact = verify_artifact(saved, published, version, source_ref)
        if published['commit'] != upstream_commit:
            raise ValueError('Existing release belongs to another source')
        record = published
    else:
        if not existing:
            gh('release', 'create', tag, '--repo', repository, '--draft', '--target', 'main',
               '--title', f'Hermes Desktop Light {version}', '--notes',
               f'Unofficial unsigned Windows x64 Light build from {UPSTREAM}@{upstream_commit}. '
               'Remote-only; no Python/local agent. Scoop owns updates. See provenance.json for build and smoke receipts.',
               '--latest=false')
        state = api(f'repos/{repository}/releases/tags/{quote(tag, safe="")}')
        history_manifest = root / f'{APP}.json'
        history_manifest.write_text(json.dumps(manifest(version, repository, record['sha256']), indent=4) + '\n', encoding='utf-8')
        for file in (artifact, root / 'provenance.json', history_manifest):
            prior = next((asset for asset in state['assets'] if asset['name'] == file.name), None)
            if prior:
                with tempfile.TemporaryDirectory() as scratch:
                    gh('release', 'download', tag, '--repo', repository, '--pattern', file.name, '--dir', scratch)
                    if (Path(scratch) / file.name).read_bytes() != file.read_bytes():
                        raise ValueError('Existing draft asset differs; refusing overwrite')
            else:
                gh('release', 'upload', tag, str(file), '--repo', repository)
        gh('release', 'edit', tag, '--repo', repository, '--draft=false', '--prerelease=false', '--latest=false')
    state = api(f'repos/{repository}/releases/tags/{quote(tag, safe="")}')
    if state['draft'] or state['prerelease']:
        raise ValueError('Release publication did not read back as stable')
    digest = record['sha256']
    data = manifest(version, repository, digest)
    url = data['architecture']['64bit']['url']
    with urllib.request.urlopen(url, timeout=120) as response:
        hasher = hashlib.sha256()
        while chunk := response.read(1024 * 1024):
            hasher.update(chunk)
    if hasher.hexdigest() != digest:
        raise ValueError('Public release URL has wrong digest; manifest left unchanged')
    transition = None
    target = Path(f'bucket/{APP}.json')
    if target.exists():
        current_version = json.loads(target.read_text(encoding='utf-8'))['version']
        if distribution_version_key(current_version)[0] == 0:
            transition = {
                'schema': 1,
                'channel': 'stable',
                'from': 'development',
                'stableVersion': version,
                'stableReleaseTag': tag,
                'upstream': UPSTREAM,
                'upstreamCommit': record['commit'],
                'sha256': digest,
            }
    _writeback(data, version, 'stable', repository, transition=transition)


def publish():
    _trusted_publish_gate()
    if os.environ.get('CHANNEL', 'stable') == 'development':
        return _publish_development()
    return _publish_stable()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['plan', 'publish'])
    args = parser.parse_args()
    {'plan': plan, 'publish': publish}[args.command]()
