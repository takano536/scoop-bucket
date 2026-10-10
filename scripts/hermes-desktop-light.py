#!/usr/bin/env python3
"""Plan, verify, and publish an unofficial Light build for an official Desktop release."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distribution import (  # noqa: E402
    artifact_name,
    desktop_version_key,
    distribution_version_key,
    light_version_key,
    package_version,
    release_tag,
)

UPSTREAM = "NousResearch/hermes-agent"
APP = "hermes-desktop-light"
DESKTOP_PUBLIC_BASE = "https://hermes-assets.nousresearch.com"
DESKTOP_FEED_URL = f"{DESKTOP_PUBLIC_BASE}/releases/win32/canary/canary.appinstaller"
DESKTOP_FEED_PATH = "releases/win32/canary/canary.appinstaller"
DESKTOP_VERSION_PATTERN = r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
CANARY_TAG = re.compile(r"^v[^+\s]+\+canary\.(20\d{6}T\d{6}Z)$")
FULL_SHA = re.compile(r"^[a-f0-9]{40}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
RELEASE_POINTER = Path("metadata/hermes-desktop-light-release.json")
NOTICE_PATHS = {
    "upstreamLicense": "LICENSE",
    "thirdParty": "THIRD-PARTY-NOTICES.txt",
    "unofficial": "UNOFFICIAL-BUILD.txt",
}

# The managed upstream builder contract is deliberately checked at the exact
# source commit selected from the official Desktop feed.  No fallback to main
# is permitted.
CONDITION_REQUIRED_INPUTS = (
    "scripts/hermes-desktop-light.py",
    "scripts/build-hermes-desktop-light.ps1",
    "scripts/smoke-hermes-desktop-light.cjs",
    "scripts/accept-hermes-desktop-light.ps1",
    "scripts/hermes-desktop-light-notices.py",
    "scripts/hermes-desktop-light-bundle-graph.mjs",
    "scripts/hermes-desktop-light-license-overrides.json",
    "scripts/distribution.py",
    ".github/workflows/hermes-desktop-light.yml",
)


class ProvenanceError(RuntimeError):
    """The official Desktop publication cannot be mapped to immutable source."""


def _repository(repository: str) -> str:
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        raise ValueError("Invalid repository identity")
    return repository


def _commit(value: str) -> str:
    if not FULL_SHA.fullmatch(value or ""):
        raise ValueError("Invalid upstream commit identity")
    return value


def _digest(value: str) -> str:
    if not SHA256.fullmatch(value or ""):
        raise ValueError("Invalid artifact digest")
    return value


def _download_url(repository: str, tag: str, name: str) -> str:
    return f"https://github.com/{_repository(repository)}/releases/download/{quote(tag, safe='')}/{name}"


def _light_executable() -> str:
    # The official canary product identity appends -canary to the executable.
    return "hermes-light-canary.exe"


def manifest(version: str, repository: str, digest: str, *, executable: str = _light_executable()) -> dict:
    """Return the installable manifest for one immutable unofficial build."""
    light_version_key(version)
    digest = _digest(digest)
    name = artifact_name(APP, version)
    tag = release_tag(APP, version)
    pointer = f"https://raw.githubusercontent.com/{_repository(repository)}/main/{RELEASE_POINTER.as_posix()}"
    return {
        "version": version,
        "description": "Hermes Desktop Light unofficial remote-only build from an official Hermes Desktop canary",
        "homepage": "https://github.com/NousResearch/hermes-agent",
        "license": "MIT",
        "architecture": {"64bit": {"url": _download_url(repository, tag, name), "hash": digest}},
        "shortcuts": [[executable, "Hermes Desktop Light (Unofficial)"]],
        "checkver": {
            "url": pointer,
            "regex": r'"version"\s*:\s*"(?<version>\d+\.\d+\.\d+\.\d+-alpha\.dev\.[1-9]\d*-r[1-9]\d*)"',
        },
        "autoupdate": {
            "architecture": {
                "64bit": {
                    "url": f"https://github.com/{_repository(repository)}/releases/download/{APP}%2Fv$matchVersion/{APP}-$matchVersion-windows-x64.zip",
                    "hash": {"url": pointer, "jsonpath": "$.sha256"},
                }
            },
            "shortcuts": [[_light_executable(), "Hermes Desktop Light (Unofficial)"]],
        },
        "notes": (
            "Unofficial unsigned x64 Light build based on the officially published Hermes Desktop "
            "canary source. The upstream source channel and this bucket's unofficial Light distribution "
            "are separate; no local Python or agent is bundled. Connect to an existing Hermes gateway."
        ),
    }


def release_pointer(
    *,
    version: str,
    digest: str,
    commit: str,
    desktop_version: str,
    desktop_tag: str,
    desktop_feed_url: str,
    desktop_feed_etag: str,
    desktop_feed_last_modified: str,
    desktop_artifact_url: str,
    desktop_artifact_sha256: str,
    conditions_fingerprint: str,
    license_sha256: str,
    release_tag_value: str,
    artifact: str,
    bucket_commit: str = "",
) -> dict:
    light_version_key(version)
    _digest(digest)
    _commit(commit)
    desktop_version_key(desktop_version)
    _digest(desktop_artifact_sha256)
    _digest(conditions_fingerprint)
    _digest(license_sha256)
    if bucket_commit:
        _commit(bucket_commit)
    return {
        "schema": 2,
        "channel": "desktop-release",
        "distribution": "unofficial-light",
        "upstreamChannel": "canary",
        "version": version,
        "sha256": digest,
        "commit": commit,
        "shortSha": commit[:7],
        "desktopVersion": desktop_version,
        "desktopTag": desktop_tag,
        "desktopFeedUrl": desktop_feed_url,
        "desktopFeedEtag": desktop_feed_etag,
        "desktopFeedLastModified": desktop_feed_last_modified,
        "desktopArtifactUrl": desktop_artifact_url,
        "desktopArtifactSha256": desktop_artifact_sha256,
        "releaseTag": release_tag_value,
        "artifact": artifact,
        "executable": _light_executable(),
        "conditionsFingerprint": conditions_fingerprint,
        "bucketCommit": bucket_commit,
        "licenseSha256": license_sha256,
    }


def provenance_manifest(record: dict, repository: str) -> dict:
    return manifest(record["version"], repository, record["sha256"], executable=record["executable"])


def gh(*args: str) -> str:
    return subprocess.check_output(["gh", *args], text=True, encoding="utf-8", stderr=subprocess.PIPE)


def api(endpoint: str, *args: str) -> dict | list:
    return json.loads(gh("api", endpoint, *args))


def _http(url: str, method: str = "GET") -> tuple[bytes, dict[str, str]]:
    request = Request(url, method=method, headers={"User-Agent": "takano536-scoop-bucket"})
    try:
        with urlopen(request, timeout=60) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            return (response.read() if method != "HEAD" else b""), headers
    except (HTTPError, URLError, TimeoutError) as exc:
        raise ProvenanceError(f"Official Desktop distribution request failed: {url}: {exc}") from exc


def _json_url(url: str) -> tuple[dict, dict[str, str]]:
    body, headers = _http(url)
    try:
        value = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"Official Desktop metadata is not valid JSON: {url}") from exc
    if not isinstance(value, dict):
        raise ProvenanceError(f"Official Desktop metadata is not an object: {url}")
    return value, headers


def _is_not_found_error(error: subprocess.CalledProcessError) -> bool:
    stderr = error.stderr or ""
    return "(HTTP 404)" in stderr or re.search(r'"status"\s*:\s*"?404"?', stderr) is not None


def _repository_tags() -> list[dict]:
    try:
        pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{UPSTREAM}/tags?per_page=100"))
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise ProvenanceError("Could not list upstream tags for Desktop release mapping") from exc
    if not isinstance(pages, list):
        raise ProvenanceError("Upstream tags response is not paginated JSON")
    rows = [row for page in pages for row in page] if all(isinstance(page, list) for page in pages) else pages
    if not all(isinstance(row, dict) for row in rows):
        raise ProvenanceError("Upstream tags response contains invalid rows")
    return rows


def _desktop_feed() -> dict:
    body, headers = _http(DESKTOP_FEED_URL)
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise ProvenanceError("Official Desktop AppInstaller feed is not valid XML") from exc
    main = root.find("{*}MainBundle")
    if main is None:
        raise ProvenanceError("Official Desktop feed has no MainBundle")
    version = root.attrib.get("Version")
    if version != main.attrib.get("Version"):
        raise ProvenanceError("Official Desktop feed has mismatched root and bundle versions")
    if not re.fullmatch(DESKTOP_VERSION_PATTERN, version or ""):
        raise ProvenanceError(f"Official Desktop product version is not a four-component version: {version!r}")
    desktop_version_key(version)
    artifact_url = main.attrib.get("Uri", "")
    expected_prefix = f"{DESKTOP_PUBLIC_BASE}/releases/win32/canary/HermesBundled-"
    expected_suffix = "-win.msixbundle"
    if not (artifact_url.startswith(expected_prefix) and artifact_url.endswith(expected_suffix)):
        raise ProvenanceError("Official Desktop feed points outside the known canary artifact layout")
    if artifact_url != f"{expected_prefix}{version}{expected_suffix}":
        raise ProvenanceError("Official Desktop feed artifact does not match its product version")
    _, artifact_headers = _http(artifact_url, method="HEAD")
    return {
        "desktopVersion": version,
        "desktopFeedUrl": DESKTOP_FEED_URL,
        "desktopFeedEtag": headers.get("etag", ""),
        "desktopFeedLastModified": headers.get("last-modified", ""),
        "desktopArtifactUrl": artifact_url,
        "desktopArtifactSize": int(artifact_headers.get("content-length", "0") or 0),
        "desktopArtifactEtag": artifact_headers.get("etag", ""),
        "desktopArtifactLastModified": artifact_headers.get("last-modified", ""),
    }


def _tag_for_product_version(version: str) -> str:
    yy, month_day, hour, minute_second = desktop_version_key(version)
    stamp = f"20{yy:02d}{month_day:04d}T{hour:02d}{minute_second:04d}Z"
    matches = []
    for row in _repository_tags():
        tag = row.get("name", "")
        match = CANARY_TAG.fullmatch(tag)
        if match and match.group(1) == stamp:
            matches.append(tag)
    if len(matches) != 1:
        raise ProvenanceError(
            f"Official Desktop product version {version} maps to {len(matches)} upstream canary tags; refusing to guess"
        )
    return matches[0]


def _desktop_provenance(feed: dict) -> dict:
    tag = _tag_for_product_version(feed["desktopVersion"])
    encoded_tag = quote(tag, safe="")
    ref = api(f"repos/{UPSTREAM}/git/ref/tags/{encoded_tag}")
    obj = ref.get("object", {}) if isinstance(ref, dict) else {}
    if obj.get("type") != "tag" or not FULL_SHA.fullmatch(obj.get("sha", "")):
        raise ProvenanceError(f"Desktop canary tag {tag} is not an immutable annotated tag")
    tag_object = api(f"repos/{UPSTREAM}/git/tags/{obj['sha']}")
    peeled = tag_object.get("object", {}) if isinstance(tag_object, dict) else {}
    commit = _commit(peeled.get("sha", "")) if peeled.get("type") == "commit" else ""
    if not commit:
        raise ProvenanceError(f"Desktop canary tag {tag} did not resolve to a commit")

    archive_base = f"{DESKTOP_PUBLIC_BASE}/releases/tag/{encoded_tag}"
    handoff_url = f"{archive_base}/handoff-windows-universal.json"
    handoff, handoff_headers = _json_url(handoff_url)
    if (
        handoff.get("schema") != 1
        or handoff.get("tag") != tag
        or handoff.get("commit") != commit
        or handoff.get("name") != "windows-universal"
    ):
        raise ProvenanceError("Desktop handoff receipt does not bind the official tag and source commit")
    files = handoff.get("files")
    if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
        raise ProvenanceError("Desktop handoff receipt has no unique Windows universal artifact")
    file_row = files[0]
    expected_name = f"HermesBundled-{feed['desktopVersion']}-win.msixbundle"
    if file_row.get("path") != expected_name:
        raise ProvenanceError("Desktop handoff artifact does not match the published feed version")
    artifact_sha = _digest(file_row.get("sha256", ""))
    artifact_size = int(file_row.get("size", 0))
    if artifact_size <= 0 or feed.get("desktopArtifactSize") != artifact_size:
        raise ProvenanceError("Desktop feed artifact size differs from its immutable handoff receipt")
    archive_artifact_url = f"{archive_base}/{quote(expected_name, safe='')}"
    _, archive_artifact_headers = _http(archive_artifact_url, method="HEAD")
    archive_size = int(archive_artifact_headers.get("content-length", "0") or 0)
    if archive_size != artifact_size:
        raise ProvenanceError("Official feed and immutable tag archive artifact sizes differ")
    feed_etag = feed.get("desktopArtifactEtag", "")
    archive_etag = archive_artifact_headers.get("etag", "")
    if feed_etag and archive_etag and feed_etag != archive_etag:
        raise ProvenanceError("Official feed and immutable tag archive artifact ETags differ")
    metadata_url = f"{archive_base}/metadata-windows-x64.json"
    metadata, metadata_headers = _json_url(metadata_url)
    expected_metadata = {
        "commit": commit,
        "tag": tag,
        "platform": "windows",
        "arch": "x64",
        "version": feed["desktopVersion"],
        "executableVersion": feed["desktopVersion"],
    }
    if any(metadata.get(key) != value for key, value in expected_metadata.items()):
        raise ProvenanceError("Desktop package metadata does not match the official feed and source tag")
    return {
        **feed,
        "desktopTag": tag,
        "desktopCommit": commit,
        "desktopTagObject": obj["sha"],
        "desktopArtifactSha256": artifact_sha,
        "desktopArtifactSize": artifact_size,
        "desktopArtifactArchiveUrl": archive_artifact_url,
        "desktopHandoffUrl": handoff_url,
        "desktopHandoffSha256": hashlib.sha256(json.dumps(handoff, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "desktopHandoffEtag": handoff_headers.get("etag", ""),
        "desktopHandoffLastModified": handoff_headers.get("last-modified", ""),
        "desktopMetadataUrl": metadata_url,
        "desktopMetadataEtag": metadata_headers.get("etag", ""),
        "desktopMetadataLastModified": metadata_headers.get("last-modified", ""),
        "desktopSourceUrl": DESKTOP_FEED_URL,
        "upstreamTagUrl": f"https://github.com/{UPSTREAM}/tree/{quote(tag, safe='')}" ,
    }


def supports_light(commit: str) -> bool:
    """Return whether the exact release source has the managed Light contract."""
    commit = _commit(commit)
    contract = {
        "apps/desktop/product-identity.cjs": (
            "hermes-light",
            "windowsExecutableName",
            "light-canary",
        ),
        "scripts/bundles/desktop.py": (
            'add_argument("--commit"',
            'add_argument("--variant"',
            'choices=["bundled", "store", "light"]',
            "build_prepared",
        ),
    }
    sources = {}
    for path in contract:
        try:
            record = api(f"repos/{UPSTREAM}/contents/{path}?ref={commit}")
        except subprocess.CalledProcessError as exc:
            if _is_not_found_error(exc):
                print(f"::notice::Unsupported Desktop release {commit}: source lacks {path}")
                return False
            raise
        try:
            encoded = "".join(str(record["content"]).split())
            sources[path] = base64.b64decode(encoded, validate=True).decode("utf-8")
        except (KeyError, ValueError, UnicodeDecodeError) as exc:
            raise ProvenanceError(f"Cannot read managed Light contract file: {path}") from exc
    missing = [
        f"{path}:{marker}"
        for path, markers in contract.items()
        for marker in markers
        if marker not in sources[path]
    ]
    if missing:
        print(f"::notice::Unsupported Desktop release {commit}: source lacks Light contract ({', '.join(missing)})")
        return False
    return True


def license_sha(commit: str) -> str:
    commit = _commit(commit)
    record = api(f"repos/{UPSTREAM}/license?ref={commit}")
    if record.get("license", {}).get("spdx_id") != "MIT":
        raise ValueError("Upstream exact Desktop release commit is not MIT licensed")
    try:
        content = base64.b64decode("".join(str(record["content"]).split()), validate=True)
    except (KeyError, ValueError) as exc:
        raise ValueError("Upstream exact Desktop release has no readable LICENSE") from exc
    if not content.lstrip().startswith(b"MIT License"):
        raise ValueError("Upstream exact Desktop release LICENSE is not MIT")
    return hashlib.sha256(content).hexdigest()


def _canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _condition_input_paths(root):
    root = Path(root)
    required = [root / relative for relative in CONDITION_REQUIRED_INPUTS]
    missing = [path.relative_to(root).as_posix() for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Required Desktop-release condition inputs are missing: " + ", ".join(missing))
    paths = set((root / "scripts").glob("*hermes-desktop-light*"))
    paths.update((root / relative for relative in CONDITION_REQUIRED_INPUTS[-2:]))
    return sorted((path.relative_to(root).as_posix(), path) for path in paths)


def conditions_descriptor(commit: str, desktop_tag: str = "", package: str = "", root=None) -> dict:
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    files = {relative: hashlib.sha256(path.read_bytes()).hexdigest() for relative, path in _condition_input_paths(root)}
    bundle_env = os.environ.get("HERMES_BUNDLE_ENV_JSON", "")
    return {
        "schema": 2,
        "channel": "desktop-release",
        "upstream": UPSTREAM,
        "upstreamRef": desktop_tag,
        "commit": _commit(commit),
        "desktopVersion": package.split("-alpha.dev.", 1)[0] if package else "",
        "variant": "light",
        "target": "win32-x64",
        "buildMode": "tag",
        "runner": "windows-2025",
        "python": "3.13",
        "builderArgs": ["--tag", desktop_tag, "--variant", "light", "--dir"],
        "compression": "Compress-Archive:Optimal",
        "signing": "unsigned",
        "localPayload": False,
        "bundleEnvSha256": hashlib.sha256(bundle_env.encode("utf-8")).hexdigest(),
        "bucketInputs": files,
    }


def conditions_fingerprint(commit: str, desktop_tag: str = "", package: str = "", root=None) -> str:
    return hashlib.sha256(_canonical_json(conditions_descriptor(commit, desktop_tag, package, root))).hexdigest()


def _read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unreadable JSON metadata: {path}") from exc


def _revision(value) -> int:
    if not re.fullmatch(r"[1-9]\d*", str(value)):
        raise ValueError("Distribution revision must be a positive integer without leading zeroes")
    return int(value)


def output(**values) -> None:
    for key, value in values.items():
        print(f"{key}={value}")
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as stream:
            for key, value in values.items():
                stream.write(f"{key}={value}\n")


def _current_version() -> str | None:
    target = Path(f"bucket/{APP}.json")
    if not target.exists():
        return None
    data = _read_json(target)
    value = data.get("version") if isinstance(data, dict) else None
    if not isinstance(value, str):
        raise ValueError("Current Light manifest has no version")
    distribution_version_key(value)
    return value


def _plan_desktop() -> None:
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    feed = _desktop_feed()
    provenance = _desktop_provenance(feed)
    desktop_version = provenance["desktopVersion"]
    requested_revision = _revision(os.environ.get("BUILD_REVISION", "1"))
    explicit = os.environ.get("REVISION_EXPLICIT") == "true"
    version = package_version(desktop_version, requested_revision)
    current = _current_version()
    candidate_key = distribution_version_key(version)
    if current is not None and distribution_version_key(current) > candidate_key:
        print(f"Current manifest {current} is newer than observed Desktop release {version}; no build")
        output(build="false", channel="desktop-release", status="already-current")
        return

    pointer = _read_json(RELEASE_POINTER)
    same_release = isinstance(pointer, dict) and pointer.get("desktopTag") == provenance["desktopTag"] and pointer.get("commit") == provenance["desktopCommit"]
    fingerprint = conditions_fingerprint(provenance["desktopCommit"], provenance["desktopTag"], version)
    if same_release:
        previous_revision = _revision(pointer.get("version", "").rsplit("-r", 1)[-1]) if isinstance(pointer.get("version"), str) else 0
        if pointer.get("conditionsFingerprint") == fingerprint and requested_revision <= previous_revision:
            print("The same published Desktop build and build conditions are already current")
            output(build="false", channel="desktop-release", status="idempotent")
            return
        if requested_revision > previous_revision and not explicit:
            if event == "schedule":
                print("Same Desktop release requires explicit workflow_dispatch for a revision bump")
                output(build="false", channel="desktop-release", status="revision-required")
                return
            raise ValueError("A same-Desktop-release rebuild requires workflow_dispatch with a higher revision")
        if requested_revision <= previous_revision:
            if event == "schedule":
                print("Desktop-release build conditions changed; scheduled run waits for an explicit revision")
                output(build="false", channel="desktop-release", status="revision-required")
                return
            raise ValueError("A same-Desktop-release rebuild requires workflow_dispatch with a higher revision")
    elif requested_revision != 1:
        raise ValueError("A new Desktop release must start at distribution revision r1")
    elif not explicit and requested_revision != 1:
        raise ValueError("Distribution revisions above r1 require workflow_dispatch")

    if not supports_light(provenance["desktopCommit"]):
        reason = f"unsupported-source:{provenance['desktopTag']}:{provenance['desktopCommit']}"
        print(f"::notice::Skipping official Desktop release {provenance['desktopTag']}: {reason}")
        output(build="false", channel="desktop-release", status="unsupported", skip_reason=reason)
        return
    exact_license_sha = license_sha(provenance["desktopCommit"])
    artifact = artifact_name(APP, version)
    output(
        build="true",
        channel="desktop-release",
        status="new-desktop-release",
        ref=provenance["desktopCommit"],
        upstream_tag=provenance["desktopTag"],
        version=version,
        release_tag=release_tag(APP, version),
        artifact=artifact,
        short_sha=provenance["desktopCommit"][:7],
        license_sha=exact_license_sha,
        conditions_fingerprint=fingerprint,
        desktop_version=desktop_version,
        desktop_feed_url=provenance["desktopFeedUrl"],
        desktop_feed_etag=provenance["desktopFeedEtag"],
        desktop_feed_last_modified=provenance["desktopFeedLastModified"],
        desktop_artifact_url=provenance["desktopArtifactUrl"],
        desktop_artifact_sha256=provenance["desktopArtifactSha256"],
        desktop_handoff_url=provenance["desktopHandoffUrl"],
    )


def plan() -> None:
    # Every trigger uses the official Desktop feed.  In particular, scheduled
    # runs never resolve or build upstream main.
    _plan_desktop()


def _verify_common_stamp(archive, record: dict) -> None:
    stamp = json.loads(archive.read("resources/install-stamp.json"))
    if any(stamp.get(key) != record[key] for key in ("commit", "payload", "updateMechanism")):
        raise ValueError("Packaged provenance mismatch")


def verify_acceptance_evidence(record: dict, version: str, source_ref: str) -> None:
    path = Path(os.environ.get("ACCEPTANCE_EVIDENCE", "acceptance/acceptance.json"))
    if not path.is_file():
        raise ValueError(f"Acceptance evidence is missing: {path}")
    try:
        evidence = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Acceptance evidence is unreadable") from exc
    if evidence.get("status") != "passed":
        raise ValueError("Acceptance evidence is not passed")
    if evidence.get("sourceRef") != source_ref or evidence.get("commit") != record.get("commit"):
        raise ValueError("Acceptance evidence source identity mismatch")
    if evidence.get("bucketPackageVersion") != version:
        raise ValueError("Acceptance evidence package version mismatch")
    if evidence.get("artifact") != record.get("artifact") or evidence.get("artifactSha256") != record.get("sha256"):
        raise ValueError("Acceptance evidence artifact mismatch")


def verify_artifact(root: Path, record: dict, version: str, source_ref: str, channel="desktop-release", expected_conditions=None) -> Path:
    import zipfile

    light_version_key(version)
    source_ref = _commit(source_ref)
    expected_name = artifact_name(APP, version)
    expected = {
        "schema": 2,
        "upstream": UPSTREAM,
        "version": version,
        "sourceRef": source_ref,
        "commit": source_ref,
        "preview": False,
        "development": True,
        "channel": "desktop-release",
        "distribution": "unofficial-light",
        "upstreamChannel": "canary",
        "payload": "light",
        "updateMechanism": "external",
        "artifact": expected_name,
        "executable": _light_executable(),
        "smoke": "two native launches; renderer loaded; localStorage retained",
    }
    if channel != "desktop-release":
        raise ValueError("Only Desktop-release Light artifacts are publishable")
    if expected_conditions is not None and record.get("conditionsFingerprint") != expected_conditions:
        raise ValueError("Build conditions fingerprint mismatch")
    if any(record.get(key) != value for key, value in expected.items()):
        raise ValueError("Unverified or unsupported Light artifact cannot be published")
    _commit(record.get("commit", ""))
    _digest(record.get("sha256", ""))
    artifact = root / expected_name
    if not artifact.is_file() or hashlib.sha256(artifact.read_bytes()).hexdigest() != record["sha256"]:
        raise ValueError("Artifact digest mismatch")
    with zipfile.ZipFile(artifact) as archive:
        names = set(archive.namelist())
        required = {_light_executable(), "resources/app.asar", "LICENSE.electron.txt", "LICENSES.chromium.html", *NOTICE_PATHS.values()}
        if not required <= names or any(name.startswith("resources/agent-payload/") for name in names):
            raise ValueError("Invalid Light package contents")
        if archive.testzip() is not None:
            raise ValueError("Corrupt ZIP")
        try:
            upstream_license = archive.read("LICENSE").decode("utf-8")
        except (KeyError, UnicodeDecodeError) as exc:
            raise ValueError("Upstream license is not UTF-8") from exc
        if "MIT License" not in upstream_license or "Copyright (c) 2025 Nous Research" not in upstream_license:
            raise ValueError("Upstream MIT license is missing or unexpected")
        notices = record.get("notices")
        if not isinstance(notices, dict):
            raise ValueError("Notice traceability is missing")
        for key, path in NOTICE_PATHS.items():
            entry = notices.get(key)
            if not isinstance(entry, dict) or entry.get("path") != path or not SHA256.fullmatch(entry.get("sha256", "")):
                raise ValueError("Notice traceability is invalid")
            if hashlib.sha256(archive.read(path)).hexdigest() != entry["sha256"]:
                raise ValueError("Notice digest mismatch")
        if not isinstance(notices["thirdParty"].get("packages"), int) or notices["thirdParty"]["packages"] < 1:
            raise ValueError("Third-party notice package count is invalid")
        audit = notices.get("audit")
        if not isinstance(audit, dict) or audit.get("status") not in ("complete", "limited"):
            raise ValueError("Audit evidence is missing")
        limitations = audit.get("limitations")
        unresolved = audit.get("unresolved")
        if not isinstance(limitations, list) or not all(isinstance(item, str) and item for item in limitations):
            raise ValueError("Audit limitation evidence is invalid")
        if not isinstance(unresolved, list) or not all(isinstance(item, str) and item for item in unresolved):
            raise ValueError("Unresolved shipped-item evidence is invalid")
        if unresolved:
            raise ValueError("Unresolved shipped items block publication: " + ", ".join(unresolved))
        _verify_common_stamp(archive, record)
    return artifact


def _trusted_publish_gate() -> None:
    if (
        os.environ.get("RELEASE_ENABLED") != "true"
        or os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
        or os.environ.get("GITHUB_EVENT_NAME") not in ("schedule", "workflow_dispatch")
    ):
        raise ValueError("Publication is disabled or not a trusted main run")


def _release_rows(repository: str) -> list[dict]:
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{_repository(repository)}/releases?per_page=100"))
    return [row for page in pages for row in page]


def _writeback(data: dict, pointer: dict, version: str, repository: str) -> None:
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
    for _ in range(3):
        subprocess.run(["git", "fetch", "origin", "main"], check=True)
        subprocess.run(["git", "reset", "--hard", "origin/main"], check=True)
        target = Path(f"bucket/{APP}.json")
        if target.exists():
            current = _read_json(target)["version"]
            if distribution_version_key(current) > distribution_version_key(version):
                raise ValueError("Refusing manifest downgrade")
        target.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
        RELEASE_POINTER.parent.mkdir(parents=True, exist_ok=True)
        RELEASE_POINTER.write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")
        files = [target, RELEASE_POINTER]
        subprocess.run(["python3", "scripts/update-readme.py"], check=True)
        subprocess.run(["python3", "scripts/update-readme.py", "--check"], check=True)
        files.append(Path("README.md"))
        subprocess.run(["git", "add", *(str(file) for file in files)], check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
            return
        subprocess.run(["git", "commit", "-m", f"chore: update {APP} to {version}"], check=True)
        if subprocess.run(["git", "push", "origin", "HEAD:main"]).returncode == 0:
            return
    raise RuntimeError("Manifest push failed; published artifact is retained for retry")


def _publish_desktop() -> None:
    import tempfile
    import urllib.request

    version = os.environ["PACKAGE_VERSION"]
    source_ref = _commit(os.environ["SOURCE_REF"])
    upstream_tag = os.environ["UPSTREAM_TAG"]
    desktop_version = os.environ["DESKTOP_VERSION"]
    repository = _repository(os.environ["GITHUB_REPOSITORY"])
    expected_conditions = os.environ["CONDITIONS_FINGERPRINT"]
    license_digest = _digest(os.environ["LICENSE_SHA256"])
    if package_version(desktop_version, _revision(version.rsplit("-r", 1)[-1])) != version:
        raise ValueError("Desktop release package version is malformed")

    # Re-read the mutable feed and immutable handoff immediately before any
    # Release mutation.  A feed advancing during build is a hard failure.
    live = _desktop_provenance(_desktop_feed())
    if any(live.get(key) != expected for key, expected in {
        "desktopVersion": desktop_version,
        "desktopTag": upstream_tag,
        "desktopCommit": source_ref,
        "desktopFeedUrl": os.environ.get("DESKTOP_FEED_URL", DESKTOP_FEED_URL),
    }.items()):
        raise ProvenanceError("Official Desktop release advanced or changed during the Light build")

    root = Path("output")
    record = json.loads((root / "provenance.json").read_text(encoding="utf-8-sig"))
    verify_acceptance_evidence(record, version, source_ref)
    if record.get("licenseSha256") != license_digest:
        raise ValueError("Build license digest does not match the admitted Desktop release commit")
    artifact = verify_artifact(root, record, version, source_ref, expected_conditions=expected_conditions)
    if record.get("desktopTag") != upstream_tag or record.get("desktopVersion") != desktop_version:
        raise ValueError("Build provenance is not bound to the admitted Desktop release")

    tag = release_tag(APP, version)
    rows = _release_rows(repository)
    existing = next((row for row in rows if row.get("tag_name") == tag), None)
    if not existing:
        notes = (
            f"Unofficial Hermes Desktop Light build for officially published Desktop {desktop_version}.\n\n"
            f"Official Desktop distribution source: {live['desktopSourceUrl']}\n"
            f"Official Desktop tag: `{upstream_tag}`\n"
            f"Upstream commit: `{source_ref}`\n"
            f"Bucket build commit: `{record.get('bucketCommit', 'unknown')}`\n"
            f"Desktop package SHA256: `{live['desktopArtifactSha256']}`\n"
            f"Light artifact SHA256: `{record['sha256']}`\n\n"
            "This is an unofficial unsigned Light build; the upstream source is a published canary and "
            "the bucket distribution is not an official Light asset. It contains no local Python or agent."
        )
        created = api(
            f"repos/{repository}/releases",
            "--method", "POST",
            "--field", f"tag_name={tag}",
            "--field", "target_commitish=main",
            "--field", f"name=Unofficial Hermes Desktop Light {version}",
            "--field", f"body={notes}",
            "--field", "draft=true",
            "--field", "prerelease=true",
            "--field", "make_latest=false",
        )
        if (
            not isinstance(created, dict)
            or created.get("tag_name") != tag
            or created.get("draft") is not True
            or created.get("prerelease") is not True
        ):
            raise ValueError("Created Light draft release response did not match requested release")
        existing = created
    release_id = existing.get("id")
    if not isinstance(release_id, int):
        raise ValueError("Light draft release has no immutable release id")
    state = api(f"repos/{repository}/releases/{release_id}")
    history_manifest = root / f"{APP}.json"
    history_manifest.write_text(json.dumps(provenance_manifest(record, repository), indent=4) + "\n", encoding="utf-8")
    for file in (artifact, root / "provenance.json", history_manifest):
        prior = next((asset for asset in state.get("assets", []) if asset.get("name") == file.name), None)
        if prior:
            with tempfile.TemporaryDirectory() as scratch:
                gh("release", "download", tag, "--repo", repository, "--pattern", file.name, "--dir", scratch)
                if (Path(scratch) / file.name).read_bytes() != file.read_bytes():
                    raise ValueError(f"Existing Release asset differs; refusing overwrite: {file.name}")
        else:
            gh("release", "upload", tag, str(file), "--repo", repository)
    gh("release", "edit", tag, "--repo", repository, "--draft=false", "--prerelease=true", "--latest=false")
    state = api(f"repos/{repository}/releases/tags/{quote(tag, safe='')}")
    if state.get("draft") or not state.get("prerelease"):
        raise ValueError("Light Release publication did not read back as prerelease")
    url = provenance_manifest(record, repository)["architecture"]["64bit"]["url"]
    with urllib.request.urlopen(url, timeout=120) as response:
        hasher = hashlib.sha256()
        while chunk := response.read(1024 * 1024):
            hasher.update(chunk)
    if hasher.hexdigest() != record["sha256"]:
        raise ValueError("Public Light Release URL has wrong digest; manifest left unchanged")
    data = provenance_manifest(record, repository)
    pointer = release_pointer(
        version=version,
        digest=record["sha256"],
        commit=source_ref,
        desktop_version=desktop_version,
        desktop_tag=upstream_tag,
        desktop_feed_url=live["desktopFeedUrl"],
        desktop_feed_etag=live["desktopFeedEtag"],
        desktop_feed_last_modified=live["desktopFeedLastModified"],
        desktop_artifact_url=live["desktopArtifactUrl"],
        desktop_artifact_sha256=live["desktopArtifactSha256"],
        conditions_fingerprint=expected_conditions,
        license_sha256=license_digest,
        release_tag_value=tag,
        artifact=record["artifact"],
        bucket_commit=record.get("bucketCommit", ""),
    )
    _writeback(data, pointer, version, repository)


def publish() -> None:
    _trusted_publish_gate()
    _publish_desktop()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "publish"))
    args = parser.parse_args(argv)
    try:
        {"plan": plan, "publish": publish}[args.command]()
    except ProvenanceError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"::error::GitHub API command failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
