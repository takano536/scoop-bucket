#!/usr/bin/env python3
"""Generate the license and provenance files shipped in Hermes Desktop Light."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import shutil
import struct
import tarfile
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

UPSTREAM = "NousResearch/hermes-agent"
THIRD_PARTY_FILE = "THIRD-PARTY-NOTICES.txt"
UNOFFICIAL_FILE = "UNOFFICIAL-BUILD.txt"
BUNDLE_GRAPH_FILE = "hermes-bundle-module-graph.json"

# NPM packages normally carry one of these files. Keep LICENSE and NOTICE
# separate: a NOTICE file contains attribution text, not the license terms.
LICENSE_FILE = re.compile(r"^(?:licen[cs]e|copying)(?:[._ -].*)?$", re.I)
NOTICE_FILE = re.compile(r"^notice(?:[._ -].*)?$", re.I)
OVERRIDES_FILE = Path(__file__).with_name("hermes-desktop-light-license-overrides.json")
ASSET_OVERRIDES_FILE = Path(__file__).with_name("hermes-desktop-light-asset-overrides.json")
JETBRAINS_ASSET_FILE = re.compile(
    r"(?:^|/)JetBrainsMono-(?P<face>Regular|Bold|Italic)(?:-[^/]+)?\.woff2$",
    re.I,
)
FIRST_PARTY_NATIVE_ASSETS = {
    "native/win32-x64/hud-modifier-monitor.exe": (
        "apps/desktop/electron/native/hud-modifier-monitor-win.cs",
        "apps/desktop/electron/native/hud-modifier-gesture.cs",
        "apps/desktop/scripts/build-hud-modifier-monitor.mjs",
    ),
}

MIT_LICENSE_TEXT = """MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""

# A package's complete license text normally comes from package files. An
# explicitly reviewed, immutable-source override is the only no-file exception.


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def load_asset_overrides() -> dict[str, dict]:
    try:
        data = json.loads(ASSET_OVERRIDES_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read asset overrides: {ASSET_OVERRIDES_FILE}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Asset overrides must be an object: {ASSET_OVERRIDES_FILE}")
    immutable_url = re.compile(
        r"https://raw\.githubusercontent\.com/[^/]+/[^/]+/[0-9a-f]{40}/.+"
    )
    for key, entry in data.items():
        if not isinstance(key, str) or not key:
            raise RuntimeError(f"Invalid asset override key: {key!r}")
        if not isinstance(entry, dict):
            raise RuntimeError(f"Asset override must be an object: {key}")
        if entry.get("spdx") != "OFL-1.1":
            raise RuntimeError(f"Unsupported asset override SPDX id: {key}")
        copyright_line = entry.get("copyright")
        if not isinstance(copyright_line, str) or not re.search(
            r"(?i)\bcopyright\b", copyright_line
        ):
            raise RuntimeError(f"Asset override has invalid copyright line: {key}")
        try:
            pattern = re.compile(entry["pattern"], re.I)
        except (KeyError, re.error, TypeError) as exc:
            raise RuntimeError(f"Asset override has invalid filename pattern: {key}") from exc
        if pattern.groups != 1:
            raise RuntimeError(f"Asset override pattern must capture one face: {key}")
        hashes = entry.get("hashes")
        if not isinstance(hashes, dict) or set(hashes) != {"Regular", "Bold", "Italic"}:
            raise RuntimeError(f"Asset override must cover all JetBrains faces: {key}")
        for face, evidence in hashes.items():
            if not isinstance(evidence, dict):
                raise RuntimeError(f"Asset override hash evidence is invalid: {key}/{face}")
            digest = evidence.get("sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise RuntimeError(f"Asset override hash is invalid: {key}/{face}")
            if not isinstance(evidence.get("url"), str) or not immutable_url.fullmatch(evidence["url"]):
                raise RuntimeError(f"Asset override source URL is not immutable: {key}/{face}")
            if not isinstance(evidence.get("path"), str) or not evidence["path"].strip():
                raise RuntimeError(f"Asset override source path is missing: {key}/{face}")
            if not isinstance(evidence.get("retrieval"), str) or not evidence["retrieval"].strip():
                raise RuntimeError(f"Asset override source retrieval is missing: {key}/{face}")
        license_evidence = entry.get("license")
        if not isinstance(license_evidence, dict):
            raise RuntimeError(f"Asset override has no license evidence: {key}")
        if not isinstance(license_evidence.get("url"), str) or not immutable_url.fullmatch(
            license_evidence["url"]
        ):
            raise RuntimeError(f"Asset override license URL is not immutable: {key}")
        if not isinstance(license_evidence.get("sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", license_evidence["sha256"]
        ):
            raise RuntimeError(f"Asset override license SHA256 is invalid: {key}")
        if not isinstance(license_evidence.get("path"), str) or not license_evidence["path"].strip():
            raise RuntimeError(f"Asset override license path is missing: {key}")
        if not isinstance(license_evidence.get("retrieval"), str) or not license_evidence["retrieval"].strip():
            raise RuntimeError(f"Asset override license retrieval is missing: {key}")
        if not isinstance(entry.get("note"), str) or not entry["note"].strip():
            raise RuntimeError(f"Asset override has no note: {key}")
    return data


def asar_file_bytes(pack: Path, relative: str) -> bytes | None:
    """Read one small file from app.asar without extracting the archive."""
    normalized = relative.replace("\\", "/").lstrip("/")
    unpacked = pack / "resources" / "app.asar.unpacked" / "dist" / normalized
    if unpacked.is_file():
        try:
            return unpacked.read_bytes()
        except OSError as exc:
            raise RuntimeError(f"Cannot read shipped asset: {unpacked}") from exc
    asar = pack / "resources" / "app.asar"
    try:
        with asar.open("rb") as stream:
            fields = stream.read(16)
            if len(fields) != 16:
                raise RuntimeError("ASAR header is truncated")
            _, _, _, json_size = struct.unpack("<IIII", fields)
            header_end = 16 + json_size
            tree = json.loads(stream.read(json_size))
            node = tree.get("files", {})
            for part in ("dist", *Path(normalized).parts):
                node = node.get(part) if isinstance(node, dict) else None
                if not isinstance(node, dict):
                    return None
            offset = node.get("offset")
            size = node.get("size")
            if offset is None or size is None or node.get("unpacked"):
                return None
            stream.seek(header_end + int(offset))
            data = stream.read(int(size))
            if len(data) != int(size):
                raise RuntimeError(f"ASAR asset is truncated: {normalized}")
            return data
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, struct.error) as exc:
        raise RuntimeError(f"Cannot inspect packaged ASAR asset: {normalized}") from exc


def reviewed_distribution_blockers(
    bundle_graph: dict,
    pack: Path | None = None,
    asset_overrides: dict[str, dict] | None = None,
) -> list[str]:
    shipped = bundle_graph.get("shippedFiles", [])
    if not isinstance(shipped, list) or not all(isinstance(item, str) and item for item in shipped):
        raise RuntimeError("Bundle graph shipped file list is invalid")
    candidates: list[tuple[str, re.Match[str], dict]] = []
    overrides = asset_overrides
    for item in shipped:
        normalized = item.replace("\\", "/")
        match = JETBRAINS_ASSET_FILE.search(normalized)
        if not match:
            continue
        if overrides is None:
            overrides = load_asset_overrides()
        matching = [
            entry
            for entry in overrides.values()
            if re.search(entry["pattern"], normalized, re.I)
        ]
        if len(matching) != 1:
            candidates.append((normalized, match, {}))
        else:
            candidates.append((normalized, match, matching[0]))
    blockers: list[str] = []
    attributions: list[dict] = []
    fetched: dict[str, bytes] = {}
    if pack is None:
        blockers.extend(
            f"{path}: JetBrains Mono asset bytes cannot be hash-verified without the packaged payload"
            for path, _, _ in candidates
        )
    for normalized, match, entry in candidates:
        if not entry:
            blockers.append(f"{normalized}: no exact-hash JetBrains Mono asset evidence is configured")
            continue
        face = match.group("face").title()
        evidence = entry["hashes"].get(face)
        if evidence is None:
            blockers.append(f"{normalized}: no exact-hash evidence is configured for face {face}")
            continue
        try:
            asset_bytes = asar_file_bytes(pack, normalized) if pack is not None else None
        except RuntimeError as exc:
            blockers.append(f"{normalized}: {exc}")
            continue
        if asset_bytes is None:
            blockers.append(f"{normalized}: shipped JetBrains Mono asset bytes are missing")
            continue
        actual_digest = sha256_bytes(asset_bytes)
        if actual_digest != evidence["sha256"]:
            blockers.append(
                f"{normalized}: JetBrains Mono SHA256 mismatch "
                f"{actual_digest} != {evidence['sha256']}"
            )
            continue
        try:
            if evidence["url"] not in fetched:
                fetched[evidence["url"]] = fetch_evidence(evidence["url"])
            source_bytes = fetched[evidence["url"]]
            source_digest = sha256_bytes(source_bytes)
            if source_digest != evidence["sha256"]:
                blockers.append(
                    f"{normalized}: immutable JetBrains Mono source SHA256 mismatch "
                    f"{source_digest} != {evidence['sha256']}"
                )
                continue
            license_evidence = entry["license"]
            if license_evidence["url"] not in fetched:
                fetched[license_evidence["url"]] = fetch_evidence(license_evidence["url"])
            license_bytes = fetched[license_evidence["url"]]
            license_digest = sha256_bytes(license_bytes)
            if license_digest != license_evidence["sha256"]:
                blockers.append(
                    f"{normalized}: OFL license SHA256 mismatch "
                    f"{license_digest} != {license_evidence['sha256']}"
                )
                continue
            license_text = license_bytes.decode("utf-8").strip()
            required_markers = (
                "SIL OPEN FONT LICENSE Version 1.1",
                "PREAMBLE",
                "DEFINITIONS",
                "1) Neither the Font Software",
                "2) Original or Modified Versions",
                "3) No Modified Version",
                "4) The name(s) of the Copyright",
                "5) The Font Software",
                "TERMINATION",
                "DISCLAIMER",
            )
            if any(marker not in license_text for marker in required_markers):
                blockers.append(f"{normalized}: incomplete OFL-1.1 license evidence")
                continue
        except (RuntimeError, UnicodeDecodeError) as exc:
            blockers.append(f"{normalized}: {exc}")
            continue
        attributions.append(
            {
                "path": normalized,
                "sha256": actual_digest,
                "spdx": entry["spdx"],
                "copyright": entry["copyright"],
                "source": {
                    "url": evidence["url"],
                    "path": evidence["path"],
                    "sha256": evidence["sha256"],
                    "retrieval": evidence["retrieval"],
                },
                "license": {
                    "url": entry["license"]["url"],
                    "path": entry["license"]["path"],
                    "sha256": entry["license"]["sha256"],
                    "retrieval": entry["license"]["retrieval"],
                    "text": license_text,
                },
            }
        )
    bundle_graph["assetAttributions"] = attributions
    return blockers


def fetch_evidence(url: str) -> bytes:
    """Fetch one reviewed immutable evidence file for an explicit override."""
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read()
    except OSError as exc:
        raise RuntimeError(f"Cannot fetch license evidence: {url}") from exc


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read package metadata: {path}") from exc


def resolve_package(package_dir: Path, name: str) -> Path | None:
    """Resolve a package using Node's upward node_modules lookup."""
    current = package_dir
    while True:
        candidate = current / "node_modules" / name
        if (candidate / "package.json").is_file():
            return candidate.resolve()
        if current.parent == current:
            return None
        current = current.parent


def is_workspace_package(source: Path, package_dir: Path) -> bool:
    try:
        relative = package_dir.relative_to(source)
    except ValueError:
        return False
    if "node_modules" in relative.parts:
        return False
    return bool(relative.parts and relative.parts[0] in {"apps", "ui-tui", "web", "tests-js"})


def declared_license(metadata: dict) -> str:
    value = metadata.get("license")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict) and value.get("type"):
        return str(value["type"]).strip()
    values = metadata.get("licenses")
    if isinstance(values, list):
        parts = []
        for item in values:
            if isinstance(item, str):
                parts.append(item.strip())
            elif isinstance(item, dict) and item.get("type"):
                parts.append(str(item["type"]).strip())
        if parts:
            return " OR ".join(part for part in parts if part)
    return ""


def package_notice_files(package_dir: Path, matcher: re.Pattern[str]) -> list[Path]:
    """Find package-owned notices, including vendored docs but not nested packages."""
    paths = []
    for path in sorted(package_dir.rglob("*"), key=lambda item: str(item).lower()):
        if not path.is_file():
            continue
        relative = path.relative_to(package_dir)
        if "node_modules" in relative.parts:
            continue
        if matcher.fullmatch(path.name):
            paths.append(path)
    return paths


def license_files(package_dir: Path) -> list[Path]:
    return package_notice_files(package_dir, LICENSE_FILE)


def notice_files(package_dir: Path) -> list[Path]:
    return package_notice_files(package_dir, NOTICE_FILE)


def load_license_overrides() -> dict[str, dict]:
    try:
        data = json.loads(OVERRIDES_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read license overrides: {OVERRIDES_FILE}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"License overrides must be an object: {OVERRIDES_FILE}")
    immutable_url = re.compile(
        r"https://raw\.githubusercontent\.com/[^/]+/[^/]+/[0-9a-f]{40}/.+"
    )
    for key, entry in data.items():
        if not isinstance(key, str) or not key.rpartition("@")[0] or not key.rpartition("@")[2]:
            raise RuntimeError(f"Invalid license override key: {key!r}")
        if not isinstance(entry, dict):
            raise RuntimeError(f"License override must be an object: {key}")
        spdx = entry.get("spdx")
        evidence = entry.get("evidence")
        note = entry.get("note")
        if not isinstance(spdx, str) or not spdx:
            raise RuntimeError(f"License override has no SPDX id: {key}")
        if not isinstance(evidence, dict):
            raise RuntimeError(f"License override has no evidence object: {key}")
        if not isinstance(note, str) or not note.strip():
            raise RuntimeError(f"License override has no note: {key}")
        kind = evidence.get("kind")
        if kind == "declared-license-no-notice":
            if spdx != "MIT":
                raise RuntimeError(f"Declared-only override must use MIT: {key}")
            declared = entry.get("declared")
            if not isinstance(declared, dict) or declared.get("license") != spdx:
                raise RuntimeError(f"Declared-only override has invalid package license: {key}")
            if "author" not in declared or not (
                declared["author"] is None
                or isinstance(declared["author"], (str, dict))
            ):
                raise RuntimeError(f"Declared-only override has invalid package author: {key}")
            retrieval = evidence.get("retrieval")
            if not isinstance(retrieval, str) or not retrieval.strip():
                raise RuntimeError(f"Declared-only override retrieval is missing: {key}")
            tarball = evidence.get("tarball")
            if not isinstance(tarball, dict):
                raise RuntimeError(f"Declared-only override requires tarball evidence: {key}")
            if not isinstance(tarball.get("url"), str) or not tarball["url"].startswith(
                "https://registry.npmjs.org/"
            ):
                raise RuntimeError(f"Declared-only tarball URL is invalid: {key}")
            if not isinstance(tarball.get("integrity"), str) or not re.fullmatch(
                r"sha512-[A-Za-z0-9+/]+={0,2}", tarball["integrity"]
            ):
                raise RuntimeError(f"Declared-only tarball integrity is invalid: {key}")
            if not isinstance(tarball.get("sha256"), str) or not re.fullmatch(
                r"[0-9a-f]{64}", tarball["sha256"]
            ):
                raise RuntimeError(f"Declared-only tarball SHA256 is invalid: {key}")
            if not isinstance(tarball.get("path"), str) or not tarball["path"].strip():
                raise RuntimeError(f"Declared-only tarball path is missing: {key}")
            for field in ("licenseMembers", "copyrightMembers"):
                if tarball.get(field) != []:
                    raise RuntimeError(
                        f"Declared-only tarball {field} evidence must be empty: {key}"
                    )
            continue
        copyright_line = entry.get("copyright")
        if not isinstance(copyright_line, str) or not re.search(
            r"(?i)\bcopyright\b", copyright_line
        ):
            raise RuntimeError(f"License override has invalid copyright line: {key}")
        if kind not in {"attribution", "license"}:
            raise RuntimeError(f"License override evidence kind is invalid: {key}")
        url = evidence.get("url")
        digest = evidence.get("sha256")
        path = evidence.get("path")
        retrieval = evidence.get("retrieval")
        if not isinstance(url, str) or not immutable_url.fullmatch(url):
            raise RuntimeError(f"License override evidence URL is not immutable: {key}")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise RuntimeError(f"License override evidence SHA256 is invalid: {key}")
        if not isinstance(path, str) or not path.strip():
            raise RuntimeError(f"License override evidence path is missing: {key}")
        if not isinstance(retrieval, str) or not retrieval.strip():
            raise RuntimeError(f"License override evidence retrieval is missing: {key}")
        tarball = evidence.get("tarball")
        if tarball is not None:
            if not isinstance(tarball, dict):
                raise RuntimeError(f"License override tarball evidence is invalid: {key}")
            if not isinstance(tarball.get("url"), str) or not tarball["url"].startswith(
                "https://registry.npmjs.org/"
            ):
                raise RuntimeError(f"License override tarball URL is invalid: {key}")
            if not isinstance(tarball.get("integrity"), str) or not tarball["integrity"].startswith(
                "sha512-"
            ):
                raise RuntimeError(f"License override tarball integrity is invalid: {key}")
            if not isinstance(tarball.get("sha256"), str) or not re.fullmatch(
                r"[0-9a-f]{64}", tarball["sha256"]
            ):
                raise RuntimeError(f"License override tarball SHA256 is invalid: {key}")
            if not isinstance(tarball.get("path"), str) or not tarball["path"].strip():
                raise RuntimeError(f"License override tarball path is missing: {key}")
    return data


def validate_unused_overrides(overrides: dict[str, dict], used: set[str]) -> list[str]:
    """Return reviewed overrides absent from this commit's shipped inventory.

    Override entries remain strictly validated by ``load_license_overrides`` and
    an entry is consumed only for its exact ``name@version`` package.  A
    different upstream commit may legitimately ship a different dependency
    set, so unused entries are recorded rather than making that build fail.
    """
    return sorted(set(overrides) - used)


def override_license_text(
    declaration: str | None,
    name: str,
    version: str,
    overrides: dict[str, dict],
    used: set[str] | None,
) -> str | None:
    key = f"{name}@{version}"
    entry = overrides.get(key)
    if entry is None:
        return None
    expected = entry["spdx"]
    if declaration and expected != declaration:
        raise RuntimeError(
            f"License override SPDX mismatch for shipped package {key}: "
            f"{expected} != {declaration}"
        )
    if entry["evidence"]["kind"] == "declared-license-no-notice":
        return None
    if expected != "MIT":
        raise RuntimeError(f"Unsupported license override SPDX id for shipped package {key}: {expected}")
    evidence = entry["evidence"]
    evidence_bytes = fetch_evidence(evidence["url"])
    actual_digest = sha256_bytes(evidence_bytes)
    if actual_digest != evidence["sha256"]:
        raise RuntimeError(
            f"License override evidence SHA256 mismatch for shipped package {key}: "
            f"{actual_digest} != {evidence['sha256']}"
        )
    if used is not None:
        used.add(key)
    if evidence["kind"] == "license":
        try:
            terms = evidence_bytes.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise RuntimeError(f"License override evidence is not UTF-8 for shipped package {key}") from exc
        if not terms:
            raise RuntimeError(f"License override evidence is empty for shipped package {key}")
        description = "License text reproduced from the cited immutable license source."
    else:
        copyright_line = entry["copyright"]
        terms = MIT_LICENSE_TEXT.replace(
            "MIT License\n\n",
            f"MIT License\n\n{copyright_line}\n\n",
            1,
        )
        description = "License text reconstructed from the declared SPDX license and the cited copyright source."
    return "\n".join(
        [
            description,
            f"Declared SPDX license: {expected}",
            f"Copyright evidence: {entry['copyright']}",
            f"Evidence source: {evidence['url']}",
            f"Evidence path: {evidence['path']}",
            f"Evidence SHA256: {evidence['sha256']}",
            f"Evidence retrieval: {evidence['retrieval']}",
            "",
            terms,
        ]
    )


def declared_only_license_text(
    package_dir: Path,
    metadata: dict,
    name: str,
    version: str,
    entry: dict,
    used: set[str] | None,
) -> str:
    key = f"{name}@{version}"
    declared = entry["declared"]
    if metadata.get("license") != declared["license"] or metadata.get("author") != declared["author"]:
        raise RuntimeError(
            f"Declared-only package.json evidence mismatch for shipped package {key}"
        )
    tarball = entry["evidence"]["tarball"]
    tarball_bytes = fetch_evidence(tarball["url"])
    actual_sha256 = sha256_bytes(tarball_bytes)
    if actual_sha256 != tarball["sha256"]:
        raise RuntimeError(
            f"Declared-only tarball SHA256 mismatch for shipped package {key}: "
            f"{actual_sha256} != {tarball['sha256']}"
        )
    actual_integrity = "sha512-" + base64.b64encode(
        hashlib.sha512(tarball_bytes).digest()
    ).decode("ascii")
    if actual_integrity != tarball["integrity"]:
        raise RuntimeError(
            f"Declared-only tarball integrity mismatch for shipped package {key}"
        )
    try:
        with tarfile.open(fileobj=io.BytesIO(tarball_bytes), mode="r:gz") as archive:
            members = [
                member.name.replace("\\", "/").lstrip("./")
                for member in archive.getmembers()
                if member.isfile()
            ]
            package_member = next(
                (member for member in members if member == tarball["path"]),
                None,
            )
            if package_member is None:
                raise RuntimeError(
                    f"Declared-only tarball package metadata is missing for shipped package {key}"
                )
            package_info_member = archive.getmember(package_member)
            package_stream = archive.extractfile(package_info_member)
            if package_stream is None:
                raise RuntimeError(
                    f"Declared-only tarball package metadata cannot be read for shipped package {key}"
                )
            tarball_metadata = json.loads(package_stream.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, tarfile.TarError) as exc:
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"Cannot inspect declared-only tarball for shipped package {key}") from exc
    if (
        tarball_metadata.get("license") != declared["license"]
        or tarball_metadata.get("author") != declared["author"]
    ):
        raise RuntimeError(
            f"Declared-only tarball package.json evidence mismatch for shipped package {key}"
        )
    license_members = sorted(
        member
        for member in members
        if LICENSE_FILE.fullmatch(Path(member).name)
        or NOTICE_FILE.fullmatch(Path(member).name)
    )
    copyright_members = sorted(
        member
        for member in members
        if re.fullmatch(r"(?i)(?:authors?|copyright)(?:[._ -].*)?", Path(member).name)
    )
    if license_members != tarball["licenseMembers"]:
        raise RuntimeError(
            f"Declared-only tarball contains license/notice members for shipped package {key}: "
            f"{license_members}"
        )
    if copyright_members != tarball["copyrightMembers"]:
        raise RuntimeError(
            f"Declared-only tarball contains copyright members for shipped package {key}: "
            f"{copyright_members}"
        )
    if used is not None:
        used.add(key)
    author = declared["author"]
    if author is None:
        author_text = "[absent]"
    elif isinstance(author, str):
        author_text = author
    else:
        author_text = json.dumps(author, ensure_ascii=False, sort_keys=True)
    return "\n".join(
        [
            "Declared-only MIT evidence: the exact npm tarball declares MIT but "
            "distributed no license file or copyright notice.",
            "No copyright line is synthesized because the package supplied none.",
            f"Declared SPDX license: {declared['license']}",
            f"package.json license (verbatim): {declared['license']}",
            f"package.json author (verbatim): {author_text}",
            f"Exact npm tarball: {tarball['url']}",
            f"Tarball integrity: {tarball['integrity']}",
            f"Tarball SHA256: {tarball['sha256']}",
            f"Tarball package metadata path: {tarball['path']}",
            "Tarball license/notice members: none",
            "Tarball copyright/author members: none",
            f"Evidence retrieval: {entry['evidence']['retrieval']}",
            "",
            MIT_LICENSE_TEXT,
        ]
    )


def spdx_identifiers(license_name: str) -> list[str] | None:
    identifiers = re.findall(r"[A-Za-z0-9][A-Za-z0-9.+-]*", license_name)
    if not identifiers:
        return None
    normalized = []
    for identifier in identifiers:
        if identifier.upper() in {"OR", "AND", "WITH"}:
            continue
        if identifier.upper() == "WTFPL":
            normalized.append("WTFPL")
        elif identifier.upper() == "MIT":
            normalized.append("MIT")
        elif identifier.upper() == "ISC":
            normalized.append("ISC")
        elif identifier.lower() == "apache-2.0":
            normalized.append("Apache-2.0")
        elif identifier.lower() == "bsd-2-clause":
            normalized.append("BSD-2-Clause")
        elif identifier.lower() == "bsd-3-clause":
            normalized.append("BSD-3-Clause")
        elif identifier.upper() == "MPL-2.0":
            normalized.append("MPL-2.0")
        elif identifier.upper() == "0BSD":
            normalized.append("0BSD")
        elif identifier.lower() == "zlib":
            normalized.append("Zlib")
        else:
            return None
    return list(dict.fromkeys(normalized))


MPL_REQUIRED_MARKERS = (
    "Mozilla Public License Version 2.0",
    "1. Definitions",
    "2. License Grants and Conditions",
    "3. Responsibilities",
    "4. Inability to Comply Due to Statute or Regulation",
    "5. Termination",
    "6. Disclaimer of Warranty",
    "7. Limitation of Liability",
    "8. Litigation",
    "9. Miscellaneous",
    "10. Versions of the License",
    "Exhibit A - Source Code Form License Notice",
    "Exhibit B - \"Incompatible With Secondary Licenses\" Notice",
)


def has_package_copyright(text: str) -> bool:
    """Find a rights-holder line without accepting MIT boilerplate wording."""
    for line in text.splitlines():
        candidate = line.strip()
        lowered = candidate.lower()
        if "permission is hereby granted" in lowered:
            break
        if "copyright" not in lowered:
            continue
        if any(
            phrase in lowered
            for phrase in (
                "above copyright notice",
                "copyright notice and this permission",
                "copyright holders be liable",
                "copyright holder(s)",
            )
        ):
            continue
        return True
    return False


MIT_REQUIRED_MARKERS = (
    "Permission is hereby granted",
    "THE SOFTWARE IS PROVIDED",
)
MIT_GRANT_MARKERS = (
    "Permission is hereby granted",
    # Some package-supplied MIT notices use the standard short form: they
    # identify the MIT license by name and retain its complete disclaimer.
    "Licensed under the MIT license",
    "Licensed under MIT license",
)


def has_placeholder_copyright(text: str) -> bool:
    lowered = text.lower()
    return any(
        placeholder in lowered
        for placeholder in (
            "<copyright holders>",
            "[copyright holders]",
            "[year] [fullname]",
            "<year> <fullname>",
            "copyright (c) [year]",
        )
    )


def validate_license_text(
    declaration: str,
    text: str,
    name: str,
    *,
    package_supplied: bool = False,
    declared_only: bool = False,
) -> None:
    identifiers = spdx_identifiers(declaration) or []
    if "MPL-2.0" in identifiers:
        missing = [marker for marker in MPL_REQUIRED_MARKERS if marker not in text]
        if missing:
            raise RuntimeError(f"Incomplete MPL-2.0 license text for shipped package {name}")
    if "MIT" in identifiers:
        if not any(marker in text for marker in MIT_GRANT_MARKERS) or MIT_REQUIRED_MARKERS[1] not in text:
            raise RuntimeError(f"Incomplete MIT license text for shipped package {name}")
        if has_placeholder_copyright(text):
            raise RuntimeError(f"MIT license text has placeholder copyright for shipped package {name}")
        if not package_supplied and not declared_only and not has_package_copyright(text):
            raise RuntimeError(f"MIT license text has no package-specific copyright line for shipped package {name}")


def novnc_source_availability(origins: set[str]) -> str:
    if origins == {"bundle-map"}:
        location = (
            "The package's JavaScript was inlined and minified into the renderer "
            "bundle; no unmodified @novnc/novnc node_modules directory was shipped."
        )
    elif "asar" in origins or "unpacked" in origins:
        location = (
            "The package's unmodified node_modules files are shipped in the "
            "application payload; any separately bundled code remains executable form."
        )
    else:
        location = "The package's executable-form location was not classified."
    return (
        "MPL-2.0 Source Code Form availability: the unmodified source for this "
        "package is available from the exact npm tarball "
        "https://registry.npmjs.org/@novnc/novnc/-/novnc-1.7.0.tgz "
        "(SHA256 32689f18d6abe96bc6530828a6bd0b9ae33bda07c083a6575ed255b5a8f2e903) "
        "and upstream noVNC commit "
        "https://github.com/novnc/noVNC/tree/63107bd06d9e1f6136ff21aeda8cd62cbf0d433e. "
        f"{location} These locations provide the corresponding Source Code Form."
    )


def license_text(
    package_dir: Path,
    metadata: dict,
    name: str,
    overrides: dict[str, dict] | None = None,
    used_overrides: set[str] | None = None,
    source_origins: set[str] | None = None,
) -> tuple[str, str]:
    if overrides is None:
        overrides = load_license_overrides()
    version = metadata.get("version")
    if not isinstance(version, str) or not version:
        raise RuntimeError(f"Shipped package has incomplete package.json: {package_dir}")
    key = f"{name}@{version}"
    override = overrides.get(key)
    declaration = declared_license(metadata)
    if not declaration and override is not None:
        declaration = override["spdx"]
    if not declaration:
        raise RuntimeError(f"Cannot determine a license text for shipped package {name} (no declaration)")
    files = license_files(package_dir)
    notices = notice_files(package_dir)
    license_pieces = []
    notice_pieces = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as exc:
            raise RuntimeError(f"Cannot read license notice for shipped package {name}: {path}") from exc
        if text:
            license_pieces.append(f"[{path.relative_to(package_dir)}]\n{text}")
    for path in notices:
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as exc:
            raise RuntimeError(f"Cannot read NOTICE for shipped package {name}: {path}") from exc
        if text:
            notice_pieces.append(f"[{path.relative_to(package_dir)}]\n{text}")

    if override is not None and override["evidence"]["kind"] == "license":
        reconstructed = override_license_text(
            declaration,
            name,
            version,
            overrides,
            used_overrides,
        )
        expected_digest = override["evidence"]["sha256"]
        local_digests = {
            sha256_bytes(path.read_bytes())
            for path in files
            if path.is_file()
        }
        if files and expected_digest not in local_digests:
            raise RuntimeError(
                f"License override does not match the shipped license file for {key}"
            )
        text = "\n\n".join([reconstructed, *notice_pieces])
        validate_license_text(declaration, text, name, package_supplied=True)
        return declaration, text

    if not license_pieces:
        if override is not None and override["evidence"]["kind"] == "declared-license-no-notice":
            if files:
                raise RuntimeError(
                    f"Declared-only override cannot replace a shipped LICENSE file for {key}"
                )
            if notice_pieces:
                raise RuntimeError(
                    f"Declared-only override cannot replace a shipped NOTICE file for {key}"
                )
            text = declared_only_license_text(
                package_dir,
                metadata,
                name,
                version,
                override,
                used_overrides,
            )
            validate_license_text(declaration, text, name, declared_only=True)
            return declaration, text
        if not files:
            reconstructed = override_license_text(
                declaration,
                name,
                version,
                overrides,
                used_overrides,
            )
            if reconstructed is not None:
                text = "\n\n".join([reconstructed, *notice_pieces])
                validate_license_text(declaration, text, name)
                return declaration, text
        if notice_pieces:
            raise RuntimeError(f"Found NOTICE without a LICENSE text for shipped package {name}")
        raise RuntimeError(f"Cannot determine a license text for shipped package {name} ({declaration or 'no declaration'})")
    text = "\n\n".join(license_pieces + notice_pieces)
    if name == "@novnc/novnc" and source_origins is not None:
        text = f"{text}\n\n{novnc_source_availability(source_origins)}"
    validate_license_text(
        declaration,
        text,
        name,
        package_supplied=bool(license_pieces),
    )
    return declaration or "See included license file", text


def package_at_path(path: Path) -> tuple[str, Path] | None:
    """Resolve the nearest package directory for a source-map source path."""
    for ancestor in (path.parent, *path.parents):
        if ancestor.name != "node_modules":
            continue
        try:
            relative = path.relative_to(ancestor)
        except ValueError:
            continue
        parts = relative.parts
        if not parts or parts[0] == ".pnpm":
            continue
        package_parts = 2 if parts[0].startswith("@") else 1
        if len(parts) < package_parts:
            continue
        package_dir = ancestor.joinpath(*parts[:package_parts])
        package_json = package_dir / "package.json"
        if not package_json.is_file():
            continue
        metadata = read_json(package_json)
        package_name = metadata.get("name")
        if isinstance(package_name, str) and package_name:
            return package_name, package_dir.resolve()
    return None


def source_map_path(map_file: Path, source_name: str) -> Path:
    source_name = unquote(source_name.split("?", 1)[0])
    if "://" in source_name:
        parsed = urlparse(source_name)
        source_name = unquote(parsed.path)
    return (map_file.parent / source_name).resolve()


def graph_emitter_manifests(roots: list[Path]) -> list[Path]:
    return sorted(
        {
            path.resolve()
            for root in roots
            if root.is_dir()
            for path in root.rglob("graph-emitter.json")
            if path.is_file()
        },
        key=lambda item: str(item).lower(),
    )


CSS_URL = re.compile(r"""url\(\s*(?P<quote>['"]?)(?P<url>.*?)(?P=quote)\s*\)""", re.I)


def css_source_files(source: Path, roots: list[Path]) -> list[Path]:
    """Read CSS modules recorded by the controlled Vite graph emitter."""
    manifests = graph_emitter_manifests(roots)
    css_files: set[Path] = set()
    for manifest in manifests:
        metadata = read_json(manifest)
        sources = metadata.get("cssSources")
        if not isinstance(sources, list):
            raise RuntimeError(f"Bundle graph emitter has no CSS source list: {manifest}")
        for relative in sources:
            if not isinstance(relative, str) or not relative:
                raise RuntimeError(f"Bundle graph emitter has an invalid CSS source: {manifest}")
            css_file = (source / relative).resolve()
            try:
                css_file.relative_to(source)
            except ValueError as exc:
                raise RuntimeError(f"Bundle graph CSS source escapes source checkout: {relative}") from exc
            if not css_file.is_file():
                raise RuntimeError(f"Bundle graph CSS source is missing: {relative}")
            css_files.add(css_file)
    return sorted(css_files, key=lambda item: str(item).lower())

def normalize_graph_output_name(name: str) -> str:
    name = name.replace("\\", "/").lstrip("./")
    for prefix in ("dist/", "renderer/"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def source_origin_path(source: Path, origin: str) -> Path | None:
    origin = unquote(origin.split("?", 1)[0])
    if "://" in origin:
        origin = unquote(urlparse(origin).path)
    raw = Path(origin)
    candidates = (
        (raw,) if raw.is_absolute() else (
            source / raw,
            source / "apps" / "desktop" / raw,
            source / "apps" / "desktop" / "src" / raw,
            source / "apps" / "desktop" / "public" / raw,
        )
    )
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file() or resolved.is_dir():
            return resolved
    return None


def asset_source_records(source: Path, roots: list[Path]) -> dict[str, list[Path]]:
    records: dict[str, list[Path]] = {}
    for manifest in graph_emitter_manifests(roots):
        metadata = read_json(manifest)
        values = metadata.get("assetSources")
        if not isinstance(values, dict):
            raise RuntimeError(f"Bundle graph emitter has no asset source record: {manifest}")
        for output_name, origins in values.items():
            if not isinstance(output_name, str) or not output_name:
                raise RuntimeError(f"Bundle graph emitter has an invalid asset name: {manifest}")
            if not isinstance(origins, list) or not origins:
                raise RuntimeError(f"Bundle graph emitter has no origins for asset: {output_name}")
            resolved_origins: list[Path] = []
            for origin in origins:
                if not isinstance(origin, str) or not origin:
                    raise RuntimeError(f"Bundle asset has an invalid origin: {output_name}")
                path = source_origin_path(source, origin)
                if path is None:
                    raise RuntimeError(f"Bundle asset origin is missing: {origin} (asset={output_name})")
                resolved_origins.append(path)
            key = normalize_graph_output_name(output_name)
            records.setdefault(key, [])
            records[key].extend(resolved_origins)
    for output_name, origins in records.items():
        records[output_name] = sorted(set(origins), key=lambda item: str(item).lower())
    return records

def graph_emitter_script_outputs(roots: list[Path]) -> set[str]:
    outputs: set[str] = set()
    for manifest in graph_emitter_manifests(roots):
        values = read_json(manifest).get("scriptOutputs")
        if values is None:
            continue
        if not isinstance(values, list):
            raise RuntimeError(f"Bundle graph emitter has an invalid script output list: {manifest}")
        for value in values:
            if not isinstance(value, str) or not is_script_name(value):
                raise RuntimeError(f"Bundle graph emitter has an invalid script output: {manifest}")
            outputs.add(normalize_graph_output_name(value))
    return outputs

def graph_emitter_audit_limitations(roots: list[Path]) -> list[str]:
    limitations: list[str] = []
    for manifest in graph_emitter_manifests(roots):
        equivalence = read_json(manifest).get("equivalence", {})
        values = equivalence.get("limitations", []) if isinstance(equivalence, dict) else []
        if not isinstance(values, list) or not all(isinstance(value, str) and value for value in values):
            raise RuntimeError(f"Bundle graph emitter has invalid equivalence limitations: {manifest}")
        limitations.extend(values)
    return limitations

IMPORT_SPECIFIER = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*\(|\brequire\s*\(|\burl\(\s*)['"]([^'"]+)['"]"""
)


def fallback_production_packages(source: Path) -> list[tuple[str, Path]]:
    """Use app-owned source imports as a conservative fallback when maps are unavailable."""
    desktop = source / "apps" / "desktop"
    metadata = read_json(desktop / "package.json")
    declared = set(metadata.get("dependencies", {})) | set(metadata.get("optionalDependencies", {}))
    if not declared:
        return []
    found: dict[str, Path] = {}
    roots = [desktop / "src", desktop / "electron"]
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or "node_modules" in path.parts or path.suffix.lower() not in {
                ".css", ".cjs", ".js", ".jsx", ".mjs", ".ts", ".tsx"
            }:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for specifier in IMPORT_SPECIFIER.findall(text):
                candidate = specifier.replace("\\", "/")
                if "/node_modules/" in candidate:
                    candidate = candidate.split("/node_modules/", 1)[1]
                if candidate.startswith((".", "/", "#")):
                    continue
                parts = candidate.split("/")
                name = "/".join(parts[:2]) if candidate.startswith("@") and len(parts) > 1 else parts[0]
                if name not in declared:
                    continue
                package_dir = resolve_package(desktop, name)
                if package_dir is not None:
                    found[name] = package_dir
    return sorted(found.items(), key=lambda item: (item[0].lower(), str(item[1]).lower()))


def app_owned_source(source: Path, path: Path) -> bool:
    roots = (source / "apps" / "desktop", source / "scripts")
    for root in roots:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if not relative.parts or "node_modules" in relative.parts:
            return False
        if root == source / "apps" / "desktop" and relative.parts[0] in {"dist", "build", ".hermes-bundle-graph"}:
            return False
        return True
    return False

def first_party_native_asset_records(
    source: Path, shipped: set[str]
) -> dict[str, list[Path]]:
    """Record generated native outputs whose in-repo sources are verified."""
    records: dict[str, list[Path]] = {}
    source_root = source.resolve()
    for output_name, relative_sources in FIRST_PARTY_NATIVE_ASSETS.items():
        if output_name not in shipped:
            continue
        origins: list[Path] = []
        for relative in relative_sources:
            path = (source / relative).resolve()
            try:
                path.relative_to(source_root)
            except ValueError:
                origins = []
                break
            if not path.is_file() or not app_owned_source(source, path):
                origins = []
                break
            origins.append(path)
        if origins:
            records[output_name] = origins
    return records


def asset_source_packages(source: Path, records: dict[str, list[Path]]) -> list[tuple[str, Path]]:
    packages: set[tuple[str, Path]] = set()
    for output_name, origins in records.items():
        if not origins:
            raise RuntimeError(f"Bundle asset has no origins: {output_name}")
        for origin in origins:
            package = package_at_path(origin)
            if package is not None:
                packages.add(package)
            elif not app_owned_source(source, origin):
                raise RuntimeError(f"Bundle asset origin is neither package nor app-owned: {origin} (asset={output_name})")
    return sorted(packages, key=lambda item: (item[0].lower(), str(item[1]).lower()))


def css_asset_packages(css_files: list[Path]) -> list[tuple[str, Path]]:
    """Resolve package-owned assets referenced by emitted CSS source modules."""
    found: set[tuple[str, Path]] = set()
    for css_file in css_files:
        try:
            text = css_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"Cannot read bundled CSS source: {css_file}") from exc
        for match in CSS_URL.finditer(text):
            asset = unquote(match.group("url").strip())
            if not asset or asset.startswith(("data:", "#", "/", "//")):
                continue
            parsed = urlparse(asset)
            if parsed.scheme or parsed.netloc:
                continue
            package = package_at_path((css_file.parent / parsed.path).resolve())
            if package is not None:
                found.add(package)
    return sorted(found, key=lambda item: (item[0].lower(), str(item[1]).lower()))


def add_graph_package(packages: dict[tuple[str, Path], dict], package: tuple[str, Path]) -> None:
    package_name, package_dir = package
    key = (package_name, package_dir)
    entry = packages.setdefault(
        key,
        {"name": package_name, "path": str(package_dir), "modules": 0},
    )
    entry["modules"] += 1


def is_script_name(name: str) -> bool:
    return name.endswith((".js", ".mjs", ".cjs"))


def graph_output_relative(path: Path) -> str:
    normalized = path.as_posix().replace("\\", "/")
    parts = normalized.split("/")
    for marker in ("dist", "renderer"):
        if marker in parts:
            index = len(parts) - 1 - parts[::-1].index(marker)
            return "/".join(parts[index + 1:])
    return parts[-1]


def graph_script_outputs(
    map_files: list[Path],
    metafile_files: list[Path],
    audit_limitations: list[str] | None = None,
) -> set[str]:
    outputs: set[str] = set()
    audit_limitations = audit_limitations if audit_limitations is not None else []
    for map_file in map_files:
        relative = graph_output_relative(map_file)
        if relative.endswith((".js.map", ".mjs.map", ".cjs.map")):
            outputs.add(relative[:-4])
            outputs.add(Path(relative).name[:-4])
        try:
            metadata = json.loads(map_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            audit_limitations.append(f"Source map could not be read: {map_file}")
            continue
        file_name = metadata.get("file")
        if isinstance(file_name, str):
            normalized = normalize_graph_output_name(file_name)
            if is_script_name(normalized):
                outputs.add(normalized)
                outputs.add(normalized.rsplit("/", 1)[-1])
    for metafile in metafile_files:
        try:
            metadata = json.loads(metafile.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            audit_limitations.append(f"Esbuild metafile could not be read: {metafile}")
            continue
        outputs_data = metadata.get("outputs")
        if not isinstance(outputs_data, dict):
            continue
        for output_name in outputs_data:
            if not isinstance(output_name, str):
                continue
            normalized = graph_output_relative(Path(output_name))
            if is_script_name(normalized):
                outputs.add(normalized)
                outputs.add(normalized.rsplit("/", 1)[-1])
    return {normalize_graph_output_name(output) for output in outputs if output}


def validate_shipped_dist_attribution(
    source: Path,
    pack: Path,
    map_files: list[Path],
    metafile_files: list[Path],
    asset_records: dict[str, list[Path]],
    emitter_script_outputs: set[str],
    audit_limitations: list[str] | None = None,
    unresolved_items: list[str] | None = None,
) -> set[str]:
    audit_limitations = audit_limitations if audit_limitations is not None else []
    unresolved_items = unresolved_items if unresolved_items is not None else []
    shipped = shipped_dist_files(pack)
    script_outputs = graph_script_outputs(map_files, metafile_files, audit_limitations) | emitter_script_outputs
    unattributed: list[str] = []
    for relative in sorted(shipped):
        parts = Path(relative).parts
        if "node_modules" in parts:
            continue
        normalized = normalize_graph_output_name(relative)
        if normalized in script_outputs:
            continue
        if normalized.endswith((".js.map", ".mjs.map", ".cjs.map")) and normalized[:-4] in script_outputs:
            continue
        if normalized in asset_records:
            continue
        unattributed.append(normalized)
    if unattributed:
        audit_limitations.append(
            "Shipped files lacked source-map/metafile or asset-origin attribution: "
            + ", ".join(unattributed)
        )
        unresolved_items.extend(f"Unresolved shipped item: {item}" for item in unattributed)
    return shipped


def bundle_module_graph(source: Path, pack: Path | None = None) -> dict:
    """Read Vite source maps and esbuild metafiles emitted by the controlled build."""
    audit_limitations: list[str] = []
    unresolved_items: list[str] = []
    roots = [
        source / "apps" / "desktop" / "dist",
        source / "apps" / "desktop" / ".hermes-bundle-graph",
    ]
    map_files = sorted(
        {
            path.resolve()
            for root in roots
            if root.is_dir()
            for path in root.rglob("*.map")
            if path.is_file()
        },
        key=lambda item: str(item).lower(),
    )
    metafile_files = sorted(
        {
            path.resolve()
            for root in roots
            if root.is_dir()
            for path in root.rglob("*.metafile.json")
            if path.is_file()
        },
        key=lambda item: str(item).lower(),
    )
    css_output_files = {
        path.resolve()
        for root in roots
        if root.is_dir()
        for path in root.rglob("*.css")
        if path.is_file()
    }
    emitter_files = set(graph_emitter_manifests(roots))
    if css_output_files and not emitter_files:
        audit_limitations.append("CSS output has no graph-emitter manifest")
    try:
        css_files = css_source_files(source, roots)
    except RuntimeError as exc:
        audit_limitations.append(f"CSS source attribution unavailable: {exc}")
        css_files = []
    try:
        asset_records = asset_source_records(source, roots)
    except RuntimeError as exc:
        audit_limitations.append(f"Asset-origin attribution unavailable: {exc}")
        asset_records = {}
    try:
        emitter_script_outputs = graph_emitter_script_outputs(roots)
    except RuntimeError as exc:
        audit_limitations.append(f"Graph-emitter script attribution unavailable: {exc}")
        emitter_script_outputs = set()
    try:
        audit_limitations.extend(graph_emitter_audit_limitations(roots))
    except RuntimeError as exc:
        audit_limitations.append(f"Bundle equivalence audit unavailable: {exc}")
    packages: dict[tuple[str, Path], dict] = {}
    module_count = 0
    for map_file in map_files:
        try:
            metadata = json.loads(map_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            audit_limitations.append(f"Source map could not be read: {map_file}")
            continue
        sources = metadata.get("sources")
        if not isinstance(sources, list):
            continue
        for source_name in sources:
            if not isinstance(source_name, str):
                continue
            package = package_at_path(source_map_path(map_file, source_name))
            if package is None:
                continue
            package_name, package_dir = package
            key = (package_name, package_dir)
            entry = packages.setdefault(
                key,
                {"name": package_name, "path": str(package_dir), "modules": 0},
            )
            entry["modules"] += 1
            module_count += 1
    for metafile in metafile_files:
        try:
            metadata = json.loads(metafile.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            audit_limitations.append(f"Esbuild metafile could not be read: {metafile}")
            continue
        inputs = metadata.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for input_name in inputs:
            if not isinstance(input_name, str):
                continue
            input_path = Path(unquote(input_name))
            candidates = (
                ((source / "apps" / "desktop") / input_path).resolve(),
                source_map_path(metafile, input_name),
            )
            package = next(
                (
                    candidate
                    for candidate in (package_at_path(path) for path in candidates)
                    if candidate is not None
                ),
                None,
            )
            if package is None:
                continue
            package_name, package_dir = package
            key = (package_name, package_dir)
            entry = packages.setdefault(
                key,
                {"name": package_name, "path": str(package_dir), "modules": 0},
            )
            entry["modules"] += 1
            module_count += 1
    if not map_files and not metafile_files:
        audit_limitations.append("No source maps or esbuild metafiles were available")
    fallback_names: set[str] = set()
    if audit_limitations:
        try:
            for package_name, package_dir in fallback_production_packages(source):
                add_graph_package(packages, (package_name, package_dir))
                fallback_names.add(package_name)
                module_count += 1
        except RuntimeError as exc:
            audit_limitations.append(f"Production dependency fallback unavailable: {exc}")
    try:
        for package in css_asset_packages(css_files):
            add_graph_package(packages, package)
            module_count += 1
    except RuntimeError as exc:
        audit_limitations.append(f"CSS asset evidence unavailable: {exc}")
    try:
        for package in asset_source_packages(source, asset_records):
            add_graph_package(packages, package)
            module_count += 1
    except RuntimeError as exc:
        audit_limitations.append(f"Asset package evidence unavailable: {exc}")
        unresolved_items.append(f"Unresolved asset evidence: {exc}")
    first_party_assets: dict[str, list[Path]] = {}
    if pack is not None:
        shipped_files = shipped_dist_files(pack)
        first_party_assets = first_party_native_asset_records(source, shipped_files)
        for output_name, origins in first_party_assets.items():
            asset_records.setdefault(output_name, []).extend(origins)
        shipped_files = validate_shipped_dist_attribution(
            source,
            pack,
            map_files,
            metafile_files,
            asset_records,
            emitter_script_outputs,
            audit_limitations,
            unresolved_items,
        )
    else:
        shipped_files = set()
        first_party_assets = {}
    if not packages:
        audit_limitations.append("No package modules were resolved from bundle evidence")
        if pack is not None and not shipped_files:
            unresolved_items.append("Unresolved shipped item: no package modules were resolved from bundle evidence")
    for entry in packages.values():
        if entry["name"] in fallback_names:
            entry["evidence"] = "fallback-production-source"
    for entry in packages.values():
        package_dir = Path(entry["path"])
        try:
            entry["path"] = package_dir.relative_to(source).as_posix()
        except ValueError as exc:
            raise RuntimeError(f"Bundle module resolves outside source checkout: {package_dir}") from exc
    return {
        "schema": 1,
        "maps": [path.relative_to(source).as_posix() for path in map_files],
        "metafiles": [path.relative_to(source).as_posix() for path in metafile_files],
        "assetSources": {
            name: [path.relative_to(source).as_posix() for path in origins]
            for name, origins in sorted(asset_records.items())
        },
        "firstPartyAssets": [
            {
                "path": output_name,
                "license": "LICENSE",
                "sources": [path.relative_to(source).as_posix() for path in origins],
            }
            for output_name, origins in sorted(first_party_assets.items())
        ],
        "shippedFiles": sorted(shipped_files),
        "auditLimitations": sorted(set(audit_limitations)),
        "unresolvedItems": sorted(set(unresolved_items)),
        "moduleCount": module_count,
        "packages": sorted(packages.values(), key=lambda item: (item["name"].lower(), item["path"].lower())),
    }


def asar_dist_files(pack: Path) -> set[str]:
    """List every file under app.asar/dist from the ASAR header."""
    asar = pack / "resources" / "app.asar"
    try:
        with asar.open("rb") as stream:
            fields = stream.read(16)
            if len(fields) != 16:
                raise RuntimeError("ASAR header is truncated")
            _, _, _, json_size = struct.unpack("<IIII", fields)
            tree = json.loads(stream.read(json_size))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("Cannot inspect packaged ASAR header") from exc
    found: set[str] = set()
    stack = [("", tree.get("files", {}))]
    while stack:
        prefix, node = stack.pop()
        for child, value in node.items():
            path = prefix + child
            if isinstance(value, dict) and "files" in value:
                stack.append((path + "/", value["files"]))
            elif path.startswith("dist/") and isinstance(value, dict) and "offset" in value:
                found.add(path[len("dist/"):])
    return found


def unpacked_dist_files(pack: Path) -> set[str]:
    root = pack / "resources" / "app.asar.unpacked" / "dist"
    if not root.is_dir():
        return set()
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def shipped_dist_files(pack: Path) -> set[str]:
    return asar_dist_files(pack) | unpacked_dist_files(pack)


def asar_node_modules(pack: Path) -> set[str]:
    """Read package paths from the ASAR header without extracting payload bytes."""
    asar = pack / "resources" / "app.asar"
    try:
        with asar.open("rb") as stream:
            fields = stream.read(16)
            if len(fields) != 16:
                raise RuntimeError("ASAR header is truncated")
            _, _, _, json_size = struct.unpack("<IIII", fields)
            tree = json.loads(stream.read(json_size))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("Cannot inspect packaged ASAR header") from exc
    found = set()
    stack = [("", tree.get("files", {}))]
    while stack:
        prefix, node = stack.pop()
        for child, value in node.items():
            path = prefix + child
            if isinstance(value, dict) and "files" in value:
                stack.append((path + "/", value["files"]))
            elif "node_modules/" in path:
                relative = path.split("node_modules/", 1)[1]
                parts = relative.split("/")
                if len(parts) >= 2 and parts[0].startswith("@") and len(parts) >= 3:
                    found.add("/".join(parts[:2]))
                elif parts:
                    found.add(parts[0])
    return {name for name in found if name != ".hermes-product"}


def unpacked_node_modules(pack: Path) -> set[str]:
    """Find package directories physically shipped outside app.asar."""
    resources = pack / "resources"
    if not resources.is_dir():
        return set()
    found = set()
    for node_modules in resources.rglob("node_modules"):
        if not node_modules.is_dir():
            continue
        for child in node_modules.iterdir():
            if child.name.startswith("@") and child.is_dir():
                for scoped in child.iterdir():
                    if (scoped / "package.json").is_file():
                        found.add(f"{child.name}/{scoped.name}")
            elif (child / "package.json").is_file():
                found.add(child.name)
    return {name for name in found if name != ".hermes-product"}


def package_identity(package_dir: Path, metadata: dict) -> str:
    name = metadata.get("name")
    version = metadata.get("version")
    if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
        raise RuntimeError(f"Shipped package has incomplete package.json: {package_dir}")
    return name


def collect_packages(
    source: Path,
    pack: Path,
    bundle_graph: dict | None = None,
    inventory: dict | None = None,
) -> list[tuple[str, str, str, str, Path]]:
    desktop = source / "apps" / "desktop"
    read_json(desktop / "package.json")
    overrides = load_license_overrides()
    used_overrides: set[str] = set()
    asar_names = asar_node_modules(pack)
    unpacked_names = unpacked_node_modules(pack)
    bundle_graph = bundle_graph or {"packages": []}
    queue: list[tuple[Path, str, Path | None, str]] = []
    origins: dict[str, set[str]] = {}

    def enqueue(parent: Path, name: str, hint: Path | None, origin: str) -> None:
        queue.append((parent, name, hint, origin))
        origins.setdefault(name, set()).add(origin)

    for name in sorted(asar_names):
        enqueue(desktop, name, None, "asar")
    for name in sorted(unpacked_names):
        enqueue(desktop, name, None, "unpacked")
    bundle_names: set[str] = set()
    for entry in bundle_graph.get("packages", []):
        if not isinstance(entry, dict):
            raise RuntimeError("Bundle module graph contains an invalid package entry")
        name = entry.get("name")
        relative = entry.get("path")
        if not isinstance(name, str) or not isinstance(relative, str):
            raise RuntimeError("Bundle module graph package lacks name or path")
        package_hint = (source / relative).resolve()
        if not (package_hint / "package.json").is_file():
            raise RuntimeError(f"Bundle module graph package is missing: {relative}")
        bundle_names.add(name)
        enqueue(desktop, name, package_hint, "fallback-evidence" if entry.get("evidence") else "bundle-map")
    if inventory is not None:
        inventory.clear()
        inventory.update(
            {
                "asar": len(asar_names),
                "unpacked": len(unpacked_names),
                "bundleMap": len(bundle_names),
                "origins": origins,
            }
        )
    visited: set[Path] = set()
    packages = []
    license_failures: list[str] = []
    while queue:
        parent, name, hint, origin = queue.pop(0)
        package_dir = hint if hint is not None else resolve_package(parent, name)
        if package_dir is None:
            raise RuntimeError(f"Installed inventoried package is missing: {name} (origin={origin})")
        if package_dir in visited:
            continue
        visited.add(package_dir)
        metadata = read_json(package_dir / "package.json")
        package_name = package_identity(package_dir, metadata)
        package_origins = origins.get(package_name, set())
        if not is_workspace_package(source, package_dir):
            try:
                license_name, text = license_text(
                    package_dir,
                    metadata,
                    package_name,
                    overrides,
                    used_overrides,
                    package_origins,
                )
            except RuntimeError as exc:
                origin_label = ",".join(sorted(package_origins)) or origin
                license_failures.append(f"{package_name}@{metadata['version']} [origin={origin_label}]: {exc}")
            else:
                packages.append((package_name, metadata["version"], license_name, text, package_dir))
    unused_overrides = validate_unused_overrides(overrides, used_overrides)
    if inventory is not None:
        inventory["unusedOverrides"] = unused_overrides
    asset_blockers = reviewed_distribution_blockers(bundle_graph, pack)
    license_failures.extend(
        f"Reviewed distribution-condition blocker: {item}"
        for item in asset_blockers
    )
    if license_failures:
        details = "\n".join(f"- {failure}" for failure in license_failures)
        origin_details = "; ".join(
            f"{name}={','.join(sorted(origins.get(name, set())) or ['not-in-inventory'])}"
            for name in ("@novnc/novnc", "dbus-native", "dijkstrajs", "@pkgjs/parseargs")
        )
        counts = (
            f"Inventory source counts (unique package names): "
            f"asar={len(asar_names)}; unpacked={len(unpacked_names)}; bundle-map={len(bundle_names)}; "
            f"origins: {origin_details}."
        )
        raise RuntimeError(f"License validation failed for shipped packages:\n{counts}\n{details}")
    packages.sort(key=lambda item: (item[0].lower(), item[1], str(item[4]).lower()))
    return packages


def write_notices(pack: Path, source: Path, source_ref: str, commit: str, bucket_repo: str, bucket_commit: str, run_url: str) -> dict:
    source_license = source / "LICENSE"
    if not source_license.is_file():
        raise RuntimeError(f"Upstream license is missing: {source_license}")
    target_license = pack / "LICENSE"
    shutil.copyfile(source_license, target_license)
    if target_license.read_bytes() != source_license.read_bytes():
        raise RuntimeError("Copied upstream license does not match the checked-out source")

    bundle_graph = bundle_module_graph(source, pack)
    graph_target = pack / "resources" / BUNDLE_GRAPH_FILE
    graph_target.parent.mkdir(parents=True, exist_ok=True)
    graph_target.write_text(
        json.dumps(bundle_graph, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    inventory: dict = {}
    packages = collect_packages(source, pack, bundle_graph, inventory)
    graph_target.write_text(
        json.dumps(bundle_graph, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    audit_limitations = bundle_graph.get("auditLimitations", [])
    unresolved_items = bundle_graph.get("unresolvedItems", [])
    if not isinstance(audit_limitations, list) or not all(
        isinstance(item, str) and item for item in audit_limitations
    ):
        raise RuntimeError("Bundle graph audit limitations are invalid")
    if not isinstance(unresolved_items, list) or not all(
        isinstance(item, str) and item for item in unresolved_items
    ):
        raise RuntimeError("Bundle graph unresolved shipped items are invalid")
    if unresolved_items:
        details = "\n".join(f"- {item}" for item in sorted(set(unresolved_items)))
        raise RuntimeError(f"Unresolved shipped items block publication:\n{details}")
    lines = [
        "THIRD-PARTY NOTICES",
        "=======================",
        "",
        "These notices cover code present in the Hermes Desktop Light win-unpacked payload.",
        "The inventory is the union of package paths in the app.asar header, physical node_modules under resources/app.asar.unpacked/resources, and package modules or asset references identified by the emitted Vite source maps, CSS sources, asset-origin manifest, and esbuild metafiles.",
        "DevDependencies and build tooling are included only when the bundle graph proves that their modules shipped; packages listed only in package.json are not included.",
        f"Inventory source counts (unique package names): asar={inventory['asar']}; unpacked={inventory['unpacked']}; bundle-map={inventory['bundleMap']}.",
        f"Upstream repository: {UPSTREAM}",
        f"Upstream source ref: {source_ref}",
        f"Upstream commit: {commit}",
        "",
    ]
    if audit_limitations:
        lines.extend(
            [
                "Additional audit limitations (recorded evidence; not a license determination and not a publication blocker when fallback evidence resolves the target):",
                *[f"- {item}" for item in audit_limitations],
                "",
            ]
        )
    if inventory["unusedOverrides"]:
        lines.extend(
            [
                "License override entries not used by this commit's shipped inventory:",
                *[f"- {key}" for key in inventory["unusedOverrides"]],
                "",
            ]
        )
    for index, (name, version, license_name, text, package_dir) in enumerate(packages, 1):
        metadata = read_json(package_dir / "package.json")
        author = metadata.get("author")
        author_text = ""
        if isinstance(author, str) and author.strip():
            author_text = f"\nAuthor metadata: {author.strip()}"
        elif isinstance(author, dict) and author.get("name"):
            author_text = f"\nAuthor metadata: {author['name']}"
        lines.extend(
            [
                f"[{index}] {name} {version}",
                f"License: {license_name}{author_text}",
                "License text:",
                text,
                "",
                "-" * 78,
                "",
            ]
        )
    for asset in bundle_graph.get("firstPartyAssets", []):
        lines.extend(
            [
                f"[First-party asset] {asset['path']}",
                "License: Upstream LICENSE (MIT)",
                *[f"Verified source: {path}" for path in asset["sources"]],
                "",
                "-" * 78,
                "",
            ]
        )
    for asset in bundle_graph.get("assetAttributions", []):
        lines.extend(
            [
                f"[Asset] {asset['path']}",
                f"License: {asset['spdx']}",
                f"SHA256: {asset['sha256']}",
                f"Copyright: {asset['copyright']}",
                f"Immutable source: {asset['source']['url']}",
                f"Source path: {asset['source']['path']}",
                f"Source SHA256: {asset['source']['sha256']}",
                f"Source retrieval: {asset['source']['retrieval']}",
                f"License source: {asset['license']['url']}",
                f"License path: {asset['license']['path']}",
                f"License SHA256: {asset['license']['sha256']}",
                f"License retrieval: {asset['license']['retrieval']}",
                "License text:",
                asset["license"]["text"],
                "",
                "-" * 78,
                "",
            ]
        )
    third_party = pack / THIRD_PARTY_FILE
    third_party.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")

    unofficial = pack / UNOFFICIAL_FILE
    unofficial.write_text(
        "\n".join(
            [
                "Hermes Desktop Light — unofficial distribution",
                "",
                "This is an unofficial, unsigned build. It is not produced, distributed, or endorsed by Nous Research.",
                "",
                f"Upstream repository: {UPSTREAM}",
                f"Upstream source ref/tag: {source_ref}",
                f"Upstream commit: {commit}",
                f"Scoop bucket repository: {bucket_repo}",
                f"Bucket commit: {bucket_commit}",
                f"Workflow run: {run_url}",
                "",
                "License files in this package:",
                "- LICENSE: Hermes Agent upstream MIT license.",
                f"- {THIRD_PARTY_FILE}: bundled production dependency license notices.",
                f"- resources/{BUNDLE_GRAPH_FILE}: emitted bundle module inventory.",
                "- LICENSE.electron.txt: Electron license.",
                "- LICENSES.chromium.html: Chromium component licenses.",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )
    return {
        "upstream": UPSTREAM,
        "sourceRef": source_ref,
        "commit": commit,
        "bucketRepository": bucket_repo,
        "bucketCommit": bucket_commit,
        "run": run_url,
        "audit": {
            "status": "complete" if not audit_limitations else "limited",
            "limitations": audit_limitations,
            "unresolved": unresolved_items,
        },
        "licenseOverrides": {"unused": inventory["unusedOverrides"]},
        "upstreamLicense": {"path": "LICENSE", "sha256": sha256(target_license)},
        "bundleGraph": {"path": f"resources/{BUNDLE_GRAPH_FILE}", "sha256": sha256(graph_target), "modules": bundle_graph["moduleCount"]},
        "thirdParty": {
            "path": THIRD_PARTY_FILE,
            "sha256": sha256(third_party),
            "packages": len(packages),
            "inventory": {
                "asar": inventory["asar"],
                "unpacked": inventory["unpacked"],
                "bundleMap": inventory["bundleMap"],
                "unusedOverrides": inventory["unusedOverrides"],
                "auditLimitations": audit_limitations,
                "unresolved": unresolved_items,
                "assets": len(bundle_graph.get("assetAttributions", [])),
                "firstPartyAssets": len(bundle_graph.get("firstPartyAssets", [])),
            },
        },
        "unofficial": {"path": UNOFFICIAL_FILE, "sha256": sha256(unofficial)},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--bucket-repository", required=True)
    parser.add_argument("--bucket-commit", required=True)
    parser.add_argument("--run-url", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{40}", args.commit):
        raise SystemExit("upstream commit must be a full lowercase SHA")
    if not re.fullmatch(r"[a-f0-9]{40}", args.bucket_commit):
        raise SystemExit("bucket commit must be a full lowercase SHA")
    metadata = write_notices(
        args.pack,
        args.source,
        args.source_ref,
        args.commit,
        args.bucket_repository,
        args.bucket_commit,
        args.run_url,
    )
    print(json.dumps(metadata, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
