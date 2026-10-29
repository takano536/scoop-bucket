"""Version helpers for bucket-built Hermes Desktop Light distributions.

The identity of a Light package is the official Desktop build tag it was built
from: ``v<X.Y.Z>+canary.<YYYYMMDDTHHMMSSZ>`` on the canary channel and
``rc.<N>-vX.Y.Z`` on the stable channel.  A Light version keeps that official
tag verbatim and appends the bucket-controlled revision, so a Scoop version
reads exactly like the official tag it tracks.
"""
import re

# The upstream product version is the identity published by the official
# AppInstaller feed (YY.MMDD.HH.MMSS).  Keep this parser strict so a malformed
# feed can never become a Scoop version by accident.
DESKTOP_VERSION = r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
SEMVER = r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
# Official Desktop build tags.  Canary bundles are tagged with the stable
# version plus the exact build stamp; stable bundles carry an RC claim tag.
CANARY_TAG = rf"v{SEMVER}\+canary\.\d{{8}}T\d{{6}}Z"
STABLE_TAG = rf"rc\.[1-9]\d*-v{SEMVER}"
OFFICIAL_TAG = rf"(?:{STABLE_TAG}|{CANARY_TAG})"
REVISION = r"[1-9]\d*"
LIGHT_VERSION = rf"{OFFICIAL_TAG}-r{REVISION}"
# Versions published before the official-tag rule stay parseable so ordering
# across the migration, and the pointers/Releases that carry them, keep working.
LEGACY_DEV_VERSION = r"0\.0\.0-alpha\.dev\.[1-9]\d*-r[1-9]\d*"
LEGACY_CANARY_VERSION = rf"{DESKTOP_VERSION}-alpha\.dev\.[1-9]\d*-r[1-9]\d*"
LEGACY_STABLE_PRODUCT_VERSION = rf"{DESKTOP_VERSION}-r[1-9]\d*"
LEGACY_STABLE_VERSION = rf"{SEMVER}-r[1-9]\d*"
APP = r"[a-z0-9]+(?:-[a-z0-9]+)*"
FULL_SHA = r"[a-f0-9]{40}"

_CANARY_TAG = re.compile(rf"v({SEMVER})\+canary\.(\d{{8}})T(\d{{6}})Z")
_STABLE_TAG = re.compile(rf"rc\.([1-9]\d*)-v({SEMVER})")


def desktop_version_key(version):
    """Return the four numeric components of an upstream Desktop version."""
    if not re.fullmatch(DESKTOP_VERSION, version or ""):
        raise ValueError("Invalid upstream Desktop product version")
    return tuple(int(item) for item in version.split("."))


def split_version(version):
    """Return the official Desktop build tag and revision of a Light version."""
    match = re.fullmatch(rf"({OFFICIAL_TAG})-r({REVISION})", version or "")
    if not match:
        raise ValueError("Invalid Desktop Light distribution version")
    return match.group(1), int(match.group(2))


def official_tag_key(tag):
    """Return the ordering key of one official Desktop build tag."""
    # Scoop's own Compare-Version puts a ``v...`` tag above an ``rc.N-...`` tag,
    # so the channel rank keeps this key in the same order for the same version.
    canary = _CANARY_TAG.fullmatch(tag or "")
    if canary:
        major, minor, patch = (int(item) for item in canary.group(1).split("."))
        return (1, major, minor, patch, int(canary.group(2) + canary.group(3)))
    stable = _STABLE_TAG.fullmatch(tag or "")
    if stable:
        major, minor, patch = (int(item) for item in stable.group(2).split("."))
        return (0, major, minor, patch, int(stable.group(1)))
    raise ValueError("Invalid official Desktop build tag")


def light_version_key(version):
    """Return the ordering key of a current official-tag-derived Light version."""
    tag, revision = split_version(version)
    return (*official_tag_key(tag), revision)


def dev_version_key(version):
    """Parse the historical fixed-base development version."""
    match = re.fullmatch(r"0\.0\.0-alpha\.dev\.([1-9]\d*)-r([1-9]\d*)", version or "")
    if not match:
        raise ValueError("Invalid legacy development distribution version")
    return tuple(int(item) for item in match.groups())


def _validate_revision(revision):
    if not re.fullmatch(r"[1-9]\d*", str(revision)):
        raise ValueError("Distribution revision must be a positive integer")
    return int(revision)


def distribution_version_key(version):
    """Order Light versions for Scoop updates.

    Family 4 holds the current official-tag-derived versions, so they sort above
    every version published before the tag rule and a normal ``scoop update``
    moves forward through the migration.  The older families keep their
    historical ordering so already published pointers stay readable.
    """
    match = re.fullmatch(rf"({OFFICIAL_TAG})-r({REVISION})", version or "")
    if match:
        return (4, *official_tag_key(match.group(1)), int(match.group(2)))
    canary = re.fullmatch(
        rf"({DESKTOP_VERSION})-alpha\.dev\.([1-9]\d*)-r([1-9]\d*)", version or ""
    )
    if canary:
        return (
            2,
            *desktop_version_key(canary.group(1)),
            int(canary.group(2)),
            int(canary.group(3)),
        )
    stable_product = re.fullmatch(rf"({DESKTOP_VERSION})(?:-r([1-9]\d*))?", version or "")
    if stable_product:
        return (
            3,
            *desktop_version_key(stable_product.group(1)),
            0,
            int(stable_product.group(2) or 1),
        )
    dev = re.fullmatch(r"0\.0\.0-alpha\.dev\.([1-9]\d*)-r([1-9]\d*)", version or "")
    if dev:
        return (0, 0, 0, 0, 0, int(dev.group(1)), int(dev.group(2)))
    stable_legacy = re.fullmatch(rf"({SEMVER})-r([1-9]\d*)", version or "")
    if stable_legacy:
        parts = tuple(int(item) for item in stable_legacy.group(1).split("."))
        return (1, *parts, 0, int(stable_legacy.group(2)))
    raise ValueError("Invalid distribution version")


def light_package_version(version):
    """Validate a Light version from either official channel.

    Current versions carry the official Desktop build tag verbatim.  Versions
    published before that rule stay valid so the pointers and Releases already
    on main keep resolving until the next publish rewrites them.
    """
    accepted = (
        rf"(?:{LIGHT_VERSION}|{LEGACY_CANARY_VERSION}|{LEGACY_STABLE_PRODUCT_VERSION}"
        rf"|{LEGACY_STABLE_VERSION}|{LEGACY_DEV_VERSION})"
    )
    if not re.fullmatch(accepted, version or ""):
        raise ValueError("Invalid Desktop Light distribution version")
    distribution_version_key(version)
    return version


def version_key(version):
    """Return the ordering key of a Light version."""
    return distribution_version_key(version)


def package_version(official_tag, revision):
    """Build the Scoop version for one official Desktop build tag."""
    if not re.fullmatch(OFFICIAL_TAG, official_tag or ""):
        raise ValueError("Invalid official Desktop build tag")
    version = f"{official_tag}-r{_validate_revision(revision)}"
    light_package_version(version)
    return version


def _validate_app(app):
    if not re.fullmatch(APP, app):
        raise ValueError("Invalid application identity")


def _validate_sha(commit):
    if not re.fullmatch(FULL_SHA, commit):
        raise ValueError("Invalid upstream commit identity")


def release_tag(app, version):
    """Application-scoped immutable distribution tag.

    A current version carries the official Desktop build tag verbatim, so the
    Release tag and the Scoop version agree.  Versions published before that
    rule keep their historical ``<app>/v<version>`` tag because those Releases
    are immutable.
    """
    _validate_app(app)
    light_package_version(version)
    if re.fullmatch(LIGHT_VERSION, version):
        return f"{app}/{version}"
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
