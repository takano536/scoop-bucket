#!/usr/bin/env python3
"""Stable-release admission and Scoop metadata; no third-party Python packages."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

UPSTREAM = 'NousResearch/hermes-agent'
VERSION = re.compile(r'v(0|[1-9]\d{0,2})\.(0|[1-9]\d*)\.(0|[1-9]\d*)')
PREVIEW_SHA = 'a3ed4a173070e981332e4d879ff6cc8b9efd57ab'


def stable_version(release):
    tag = release.get('tag_name', '')
    if release.get('draft') is not False or release.get('prerelease') is not False:
        return None
    return tag[1:] if VERSION.fullmatch(tag) else None


def manifest(version, repository, digest):
    if not VERSION.fullmatch('v' + version) or not re.fullmatch(r'[\w.-]+/[\w.-]+', repository) or not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise ValueError('Invalid artifact identity')
    name = f'hermes-agent-light-{version}-windows-x64.zip'
    return {
        'version': version,
        'description': 'Hermes Agent remote-only desktop client (Light)',
        'homepage': 'https://github.com/NousResearch/hermes-agent',
        'license': 'MIT',
        'architecture': {'64bit': {
            'url': f'https://github.com/{repository}/releases/download/hermes-agent-light-v{version}/{name}',
            'hash': digest,
        }},
        'shortcuts': [['Hermes Light.exe', 'Hermes Agent Light']],
        'checkver': {
            'url': f'https://api.github.com/repos/{repository}/releases',
            'regex': r'"tag_name"\s*:\s*"hermes-agent-light-v(\d+\.\d+\.\d+)"',
        },
        'autoupdate': {'architecture': {'64bit': {
            'url': f'https://github.com/{repository}/releases/download/hermes-agent-light-v$version/hermes-agent-light-$version-windows-x64.zip',
        }}},
        'notes': 'Unofficial unsigned x64 build. Connect to an existing Hermes gateway; no local Python or agent is bundled. Settings remain in the application user-data directory outside Scoop.',
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
    import base64
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


def plan():
    if os.environ.get('PREVIEW') == 'true':
        if not supports_light(PREVIEW_SHA):
            output(build='false')
            return
        output(build='true', ref=PREVIEW_SHA, version='preview', claim='', claim_object='')
        return
    release = api(f'repos/{UPSTREAM}/releases/latest')
    version = stable_version(release)
    if version is None:
        print(f"Waiting for a published stable SemVer release with Light support; latest: {release['tag_name']}")
        output(build='false')
        return
    current = Path('bucket/hermes-agent-light.json')
    if current.exists() and tuple(map(int, json.loads(current.read_text())['version'].split('.'))) >= tuple(map(int, version.split('.'))):
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
    claim, claim_object = release_claim(metadata, version, commit)
    output(build='true', ref=tag, version=version, claim=claim, claim_object=claim_object)


def verify_artifact(root, record, version, source_ref):
    import zipfile
    expected = {
        'schema': 1, 'upstream': UPSTREAM, 'version': version, 'sourceRef': source_ref,
        'preview': False, 'payload': 'light', 'updateMechanism': 'external',
        'artifact': f'hermes-agent-light-{version}-windows-x64.zip',
        'executable': 'Hermes Light.exe',
        'smoke': 'two native launches; renderer loaded; localStorage retained',
    }
    if any(record.get(key) != value for key, value in expected.items()) or not re.fullmatch(r'[a-f0-9]{40}', record.get('commit', '')):
        raise ValueError('Unverified or preview artifact cannot be published')
    artifact = root / expected['artifact']
    if hashlib.sha256(artifact.read_bytes()).hexdigest() != record.get('sha256'):
        raise ValueError('Artifact digest mismatch')
    with zipfile.ZipFile(artifact) as archive:
        names = archive.namelist()
        if 'Hermes Light.exe' not in names or 'resources/app.asar' not in names or any(name.startswith('resources/agent-payload/') for name in names):
            raise ValueError('Invalid Light package contents')
        if archive.testzip() is not None:
            raise ValueError('Corrupt ZIP')
        stamp = json.loads(archive.read('resources/install-stamp.json'))
        if any(stamp.get(key) != record[key] for key in ('commit', 'payload', 'updateMechanism')):
            raise ValueError('Packaged provenance mismatch')
    return artifact


def publish():
    if (os.environ.get('RELEASE_ENABLED') != 'true' or
            os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('GITHUB_REF') != 'refs/heads/main' or
            os.environ.get('GITHUB_EVENT_NAME') not in ('schedule', 'workflow_dispatch')):
        raise ValueError('Publication is disabled or not a trusted main run')
    import tempfile
    import urllib.request
    version, source_ref = os.environ['PACKAGE_VERSION'], os.environ['SOURCE_REF']
    repository = os.environ['GITHUB_REPOSITORY']
    root = Path('output')
    record = json.loads((root / 'provenance.json').read_text(encoding='utf-8-sig'))
    artifact = verify_artifact(root, record, version, source_ref)
    upstream_commit = api(f'repos/{UPSTREAM}/commits/{source_ref}')['sha']
    if record['commit'] != upstream_commit:
        raise ValueError('Upstream tag moved or build has wrong source')
    tag = f'hermes-agent-light-v{version}'
    pages = json.loads(gh('api', '--paginate', '--slurp', f'repos/{repository}/releases?per_page=100'))
    existing = next((row for page in pages for row in page if row['tag_name'] == tag), None)
    if existing and not existing['draft']:
        # A previous publication may have succeeded before its git push failed.
        # Reuse the immutable published bytes instead of uploading a rebuilt ZIP.
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
               '--title', f'Hermes Agent Light {version}', '--notes',
               f'Unofficial unsigned Windows x64 Light build from {UPSTREAM}@{upstream_commit}. '
               'Remote-only; no Python/local agent. Scoop owns updates. See provenance.json for build and smoke receipts.',
               '--latest=false')
        state = api(f'repos/{repository}/releases/tags/{tag}')
        for file in (artifact, root / 'provenance.json'):
            prior = next((asset for asset in state['assets'] if asset['name'] == file.name), None)
            if prior:
                with tempfile.TemporaryDirectory() as scratch:
                    gh('release', 'download', tag, '--repo', repository, '--pattern', file.name, '--dir', scratch)
                    if (Path(scratch) / file.name).read_bytes() != file.read_bytes():
                        raise ValueError('Existing draft asset differs; refusing overwrite')
            else:
                gh('release', 'upload', tag, str(file), '--repo', repository)
        gh('release', 'edit', tag, '--repo', repository, '--draft=false', '--prerelease=false', '--latest=false')
    state = api(f'repos/{repository}/releases/tags/{tag}')
    if state['draft'] or state['prerelease']:
        raise ValueError('Release publication did not read back as stable')
    digest = record['sha256']
    data = manifest(version, repository, digest)
    url = data['architecture']['64bit']['url']
    # Verify the exact public URL Scoop will consume, not only the API upload.
    with urllib.request.urlopen(url, timeout=120) as response:
        hasher = hashlib.sha256()
        while chunk := response.read(1024 * 1024):
            hasher.update(chunk)
    if hasher.hexdigest() != digest:
        raise ValueError('Public release URL has wrong digest; manifest left unchanged')
    subprocess.run(['git', 'config', 'user.name', 'github-actions[bot]'], check=True)
    subprocess.run(['git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'], check=True)
    for _ in range(3):
        subprocess.run(['git', 'fetch', 'origin', 'main'], check=True)
        # Disposable Actions checkout only; always retain concurrent main changes.
        subprocess.run(['git', 'reset', '--hard', 'origin/main'], check=True)
        target = Path('bucket/hermes-agent-light.json')
        if target.exists() and tuple(map(int, json.loads(target.read_text())['version'].split('.'))) > tuple(map(int, version.split('.'))):
            raise ValueError('Refusing manifest downgrade')
        target.write_text(json.dumps(data, indent=4) + '\n', encoding='utf-8')
        subprocess.run(['python3', 'scripts/update-readme.py'], check=True)
        subprocess.run(['python3', 'scripts/update-readme.py', '--check'], check=True)
        subprocess.run(['git', 'add', str(target), 'README.md'], check=True)
        if subprocess.run(['git', 'diff', '--cached', '--quiet']).returncode == 0:
            return
        subprocess.run(['git', 'commit', '-m', f'chore: update hermes-agent-light to {version}'], check=True)
        if subprocess.run(['git', 'push', 'origin', 'HEAD:main']).returncode == 0:
            remote = api(f'repos/{repository}/contents/bucket/hermes-agent-light.json?ref=main')
            import base64
            actual = json.loads(base64.b64decode(remote['content']))
            if actual != data:
                raise ValueError('Manifest writeback readback mismatch')
            remote_readme = api(f'repos/{repository}/contents/README.md?ref=main')
            actual_readme = base64.b64decode(remote_readme['content']).decode('utf-8').replace('\r\n', '\n')
            if actual_readme != Path('README.md').read_text(encoding='utf-8'):
                raise ValueError('README writeback readback mismatch')
            return
    raise RuntimeError('Manifest push failed; published artifact is retained for retry')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['plan', 'publish'])
    args = parser.parse_args()
    {'plan': plan, 'publish': publish}[args.command]()
