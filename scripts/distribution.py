"""Shared identity rules for application-scoped community distributions."""
import re

UPSTREAM_VERSION = r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)'


def version_key(version):
    match = re.fullmatch(UPSTREAM_VERSION + r'-r([1-9]\d*)', version)
    if not match:
        raise ValueError('Invalid distribution version')
    return tuple(map(int, match.groups()))


def package_version(upstream_version, revision):
    version = f'{upstream_version}-r{revision}'
    version_key(version)
    return version


def release_tag(app, version):
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', app):
        raise ValueError('Invalid application identity')
    version_key(version)
    return f'{app}/v{version}'
