"""Version helpers for bucket-built Hermes Desktop Light distributions.

The upstream Desktop Windows product uses a four-component version such as
``26.1009.7.410`` for its published canary builds.  A bucket-built Light
package keeps that product version and appends the explicit unofficial/dev
marker plus a manually controlled distribution revision.
"""
import re

# The upstream product version is the identity published by the official
# AppInstaller feed (YY.MMDD.HH.MMSS).  Keep this parser strict so a malformed
# feed can never become a Scoop version by accident.
DESKTOP_VERSION = r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
# Retain recognition of the already-published pre-policy version so a normal
# Scoop update can move it to the first Desktop-release-derived version.
LEGACY_DEV_VERSION = r"0\.0\.0-alpha\.dev\.[1-9]\d*-r[1-9]\d*"
LIGHT_VERSION = rf"{DESKTOP_VERSION}-alpha\.dev\.[1-9]\d*-r[1-9]\d*"
# The official Desktop stable channel publishes a Store-scheme product version
# such as ``2026.6864.2132.0``. A stable-channel Light package keeps that
# product version and carries only the bucket revision, without the
# canary-only ``alpha.dev`` marker.
STABLE_LIGHT_VERSION = rf"{DESKTOP_VERSION}-r[1-9]\d*"
# Channel name -> the version marker that distinguishes the unofficial Light
# distribution from the upstream product version it was built from.
CHANNEL_VERSION_MARKERS = {"canary": "-alpha.dev.1", "stable": ""}
LEGACY_STABLE_VERSION = r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)-r[1-9]\d*"
APP = r"[a-z0-9]+(?:-[a-z0-9]+)*"
FULL_SHA = r"[a-f0-9]{40}"


def desktop_version_key(version):
    """Return the four numeric components of an upstream Desktop version."""
    if not re.fullmatch(DESKTOP_VERSION, version):
        raise ValueError("Invalid upstream Desktop product version")
    return tuple(int(item) for item in version.split("."))


def light_version_key(version):
    """Parse the current Desktop-derived Light package version."""
    match = re.fullmatch(
        rf"({DESKTOP_VERSION})-alpha\.dev\.([1-9]\d*)-r([1-9]\d*)", version
    )
    if not match:
        raise ValueError("Invalid Desktop Light distribution version")
    return (*desktop_version_key(match.group(1)), int(match.group(2)), int(match.group(3)))


def light_package_version(version):
    """Validate a Desktop-derived Light version from either official channel.

    Ordering between the two channels is owned by
    :func:`distribution_version_key`; this helper only guarantees that a
    version belongs to the unofficial Light distribution and is well formed.
    """
    if not re.fullmatch(
        rf"(?:{DESKTOP_VERSION})(?:-alpha\.dev\.1)?-r[1-9]\d*", version
    ):
        raise ValueError("Invalid Desktop Light distribution version")
    distribution_version_key(version)
    return version


def version_key(version):
    """Return numeric Desktop product, dev-marker, and revision ordering."""
    return light_version_key(version)


def dev_version_key(version):
    """Parse the historical fixed-base development version."""
    match = re.fullmatch(
        r"0\.0\.0-alpha\.dev\.([1-9]\d*)-r([1-9]\d*)", version
    )
    if not match:
        raise ValueError("Invalid legacy development distribution version")
    return tuple(int(item) for item in match.groups())


def _validate_revision(revision):
    if not re.fullmatch(r"[1-9]\d*", str(revision)):
        raise ValueError("Distribution revision must be a positive integer")
    return int(revision)



def distribution_version_key(version):
    """Order legacy versions below Desktop-derived Light versions.

    The leading family discriminator deliberately makes the first new
    Desktop-derived package greater than ``0.0.0-alpha.dev.1-r1`` while
    retaining numeric ordering for product-version, marker, and revision
    components.  Stable four-component Desktop versions are accepted for
    comparison fixtures and sort above the corresponding ``alpha.dev`` build.
    """
    try:
        product = light_version_key(version)
        return (2, *product)
    except ValueError:
        pass
    legacy = re.fullmatch(
        r"0\.0\.0-alpha\.dev\.([1-9]\d*)-r([1-9]\d*)", version
    )
    if legacy:
        return (0, 0, 0, 0, 0, int(legacy.group(1)), int(legacy.group(2)))
    stable_desktop = re.fullmatch(
        rf"({DESKTOP_VERSION})(?:-r([1-9]\d*))?", version
    )
    if stable_desktop:
        product = desktop_version_key(stable_desktop.group(1))
        # A plain product version is the official/stable form and therefore
        # sorts after the unofficial alpha.dev form.  ``-rN`` is retained for
        # bucket stable fixtures and is also above alpha.dev.
        revision = int(stable_desktop.group(2) or 1)
        return (3, *product, 0, revision)
    stable_legacy = re.fullmatch(
        r"((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))-r([1-9]\d*)",
        version,
    )
    if stable_legacy:
        parts = tuple(int(item) for item in stable_legacy.group(1).split("."))
        return (1, *parts, 0, int(stable_legacy.group(2)))
    raise ValueError("Invalid distribution version")


def package_version(upstream_desktop_version, revision, channel="canary"):
    """Build the Scoop version for one official Desktop channel.

    ``canary`` keeps the historical ``alpha.dev`` marker; ``stable`` adds only
    the bucket revision.  Both keep the upstream four-component product
    version so a normal Scoop update can move from the canary form to the
    stable form.
    """
    desktop_version_key(upstream_desktop_version)
    if channel not in CHANNEL_VERSION_MARKERS:
        raise ValueError("Unknown official Desktop channel")
    if not re.fullmatch(r"[1-9]\d*", str(revision)):
        raise ValueError("Distribution revision must be a positive integer")
    version = (
        f"{upstream_desktop_version}{CHANNEL_VERSION_MARKERS[channel]}-r{int(revision)}"
    )
    light_package_version(version)
    return version


def _validate_app(app):
    if not re.fullmatch(APP, app):
        raise ValueError("Invalid application identity")


def _validate_sha(commit):
    if not re.fullmatch(FULL_SHA, commit):
        raise ValueError("Invalid upstream commit identity")


def release_tag(app, version):
    """Application-scoped immutable distribution tag."""
    _validate_app(app)
    light_package_version(version)
    return f"{app}/v{version}"


def artifact_name(app, version, architecture="windows-x64"):
    _validate_app(app)
    light_package_version(version)
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", architecture):
        raise ValueError("Invalid artifact architecture")
    return f"{app}-{version}-{architecture}.zip"


# Explicit names used by the publisher keep call sites readable.
def light_artifact_name(app, version, architecture="windows-x64"):
    return artifact_name(app, version, architecture)
