"""Version helpers for bucket-built apps using the current three-component format.

The helper intentionally accepts only numeric ``major.minor.patch-rN`` versions.
Applications with CalVer, four-component, or another version contract need their
own parser and regression tests.
"""
import re

UPSTREAM_VERSION = r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)'
DEV_VERSION = r'0\.0\.0-alpha\.dev\.([1-9]\d*)-r([1-9]\d*)'
FULL_SHA = r'[a-f0-9]{40}'
APP = r'[a-z0-9]+(?:-[a-z0-9]+)*'


def version_key(version):
    """Return numeric stable upstream/revision ordering."""
    match = re.fullmatch(UPSTREAM_VERSION + r'-r([1-9]\d*)', version)
    if not match:
        raise ValueError('Invalid distribution version')
    return tuple(map(int, match.groups()))


def dev_version_key(version):
    """Return numeric development sequence/revision ordering."""
    match = re.fullmatch(DEV_VERSION, version)
    if not match:
        raise ValueError('Invalid development distribution version')
    return tuple(map(int, match.groups()))


def distribution_version_key(version):
    """Order development versions below every stable version."""
    try:
        return (1, *version_key(version))
    except ValueError:
        return (0, *dev_version_key(version))


def package_version(upstream_version, revision):
    version = f'{upstream_version}-r{revision}'
    version_key(version)
    return version


def dev_package_version(sequence, revision):
    version = f'0.0.0-alpha.dev.{sequence}-r{revision}'
    dev_version_key(version)
    return version


def _validate_app(app):
    if not re.fullmatch(APP, app):
        raise ValueError('Invalid application identity')


def _validate_sha(commit):
    if not re.fullmatch(FULL_SHA, commit):
        raise ValueError('Invalid upstream commit identity')


def release_tag(app, version):
    """Stable application-scoped release tag."""
    _validate_app(app)
    version_key(version)
    return f'{app}/v{version}'


def dev_release_tag(app, version, commit):
    """Development tag with full upstream SHA to prevent collisions."""
    _validate_app(app)
    dev_version_key(version)
    _validate_sha(commit)
    return f'{app}/dev/v{version}-{commit}'


def dev_artifact_name(app, version, commit, architecture='windows-x64'):
    _validate_app(app)
    dev_version_key(version)
    _validate_sha(commit)
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', architecture):
        raise ValueError('Invalid artifact architecture')
    return f'{app}-dev-{version}-{commit}-{architecture}.zip'
