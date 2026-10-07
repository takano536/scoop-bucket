#!/usr/bin/env python3
"""Generate the license and provenance files shipped in Hermes Light."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
from pathlib import Path

UPSTREAM = "NousResearch/hermes-agent"
THIRD_PARTY_FILE = "THIRD-PARTY-NOTICES.txt"
UNOFFICIAL_FILE = "UNOFFICIAL-BUILD.txt"

# NPM packages normally carry one of these files. Keep LICENSE and NOTICE
# separate: a NOTICE file contains attribution text, not the license terms.
LICENSE_FILE = re.compile(r"^(?:licen[cs]e|copying)(?:[._ -].*)?$", re.I)
NOTICE_FILE = re.compile(r"^notice(?:[._ -].*)?$", re.I)
OVERRIDES_FILE = Path(__file__).with_name("hermes-light-license-overrides.json")

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


def optional_package_names(source: Path) -> set[str]:
    """Return package names marked optional by the exact npm lockfile."""
    names: set[str] = set()
    for lockfile in (source / "package-lock.json", source / "apps" / "desktop" / "package-lock.json"):
        if not lockfile.is_file():
            continue
        metadata = read_json(lockfile)
        packages = metadata.get("packages", {})
        if not isinstance(packages, dict):
            continue
        for key, package in packages.items():
            if not isinstance(package, dict) or not package.get("optional"):
                continue
            parts = str(key).split("/node_modules/")
            name = parts[-1]
            if name.startswith("@"):
                name = "/".join(name.split("/")[:2])
            else:
                name = name.split("/", 1)[0]
            if name:
                names.add(name)
    return names


PLATFORM_PACKAGE_TOKEN = re.compile(
    r"(?:^|[-/])(aix|android|arm64|darwin|freebsd|ia32|linux|netbsd|openbsd|openharmony|ppc64|riscv64|s390x|sunos|wasm32|win32|x64)(?:[-/]|$)",
    re.I,
)


def is_platform_package(name: str) -> bool:
    return bool(PLATFORM_PACKAGE_TOKEN.search(name))


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


def license_files(package_dir: Path) -> list[Path]:
    return [
        child
        for child in sorted(package_dir.iterdir(), key=lambda item: item.name.lower())
        if child.is_file() and LICENSE_FILE.fullmatch(child.name)
    ]


def notice_files(package_dir: Path) -> list[Path]:
    return [
        child
        for child in sorted(package_dir.iterdir(), key=lambda item: item.name.lower())
        if child.is_file() and NOTICE_FILE.fullmatch(child.name)
    ]


def load_license_overrides() -> dict[str, dict]:
    try:
        data = json.loads(OVERRIDES_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read license overrides: {OVERRIDES_FILE}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"License overrides must be an object: {OVERRIDES_FILE}")
    for key, entry in data.items():
        if not isinstance(key, str) or not key.rpartition("@")[0] or not key.rpartition("@")[2]:
            raise RuntimeError(f"Invalid license override key: {key!r}")
        if not isinstance(entry, dict):
            raise RuntimeError(f"License override must be an object: {key}")
        spdx = entry.get("spdx")
        copyright_line = entry.get("copyright")
        evidence = entry.get("evidence")
        note = entry.get("note")
        if not isinstance(spdx, str) or not spdx:
            raise RuntimeError(f"License override has no SPDX id: {key}")
        if not isinstance(copyright_line, str) or not re.fullmatch(
            r"Copyright \(c\) \S.*", copyright_line
        ):
            raise RuntimeError(f"License override has invalid copyright line: {key}")
        if not isinstance(evidence, dict):
            raise RuntimeError(f"License override has no evidence object: {key}")
        url = evidence.get("url")
        digest = evidence.get("sha256")
        if not isinstance(url, str) or not re.fullmatch(
            r"https://raw\.githubusercontent\.com/[^/]+/[^/]+/[0-9a-f]{40}/.+",
            url,
        ):
            raise RuntimeError(f"License override evidence URL is not immutable: {key}")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise RuntimeError(f"License override evidence SHA256 is invalid: {key}")
        if not isinstance(note, str) or not note.strip():
            raise RuntimeError(f"License override has no note: {key}")
    return data


def validate_unused_overrides(overrides: dict[str, dict], used: set[str]) -> None:
    unused = sorted(set(overrides) - used)
    if unused:
        raise RuntimeError(f"Unused license override entries: {', '.join(unused)}")


def override_license_text(
    declaration: str,
    name: str,
    version: str,
    overrides: dict[str, dict],
    used: set[str] | None,
) -> str | None:
    key = f"{name}@{version}"
    entry = overrides.get(key)
    if entry is None:
        return None
    if entry["spdx"] != declaration:
        raise RuntimeError(
            f"License override SPDX mismatch for shipped package {key}: "
            f"{entry['spdx']} != {declaration}"
        )
    if entry["spdx"] != "MIT":
        raise RuntimeError(f"Unsupported license override SPDX id for shipped package {key}: {entry['spdx']}")
    if used is not None:
        used.add(key)
    evidence = entry["evidence"]
    copyright_line = entry["copyright"]
    terms = MIT_LICENSE_TEXT.replace(
        "MIT License\n\n",
        f"MIT License\n\n{copyright_line}\n\n",
        1,
    )
    return "\n".join(
        [
            "License text reconstructed from the declared SPDX license and the cited copyright source.",
            f"Declared SPDX license: {declaration}",
            f"Copyright evidence: {copyright_line}",
            f"Evidence source: {evidence['url']}",
            f"Evidence SHA256: {evidence['sha256']}",
            "",
            terms,
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


def validate_license_text(declaration: str, text: str, name: str) -> None:
    identifiers = spdx_identifiers(declaration) or []
    if "MPL-2.0" in identifiers:
        missing = [marker for marker in MPL_REQUIRED_MARKERS if marker not in text]
        if missing:
            raise RuntimeError(f"Incomplete MPL-2.0 license text for shipped package {name}")
    if "MIT" in identifiers and not re.search(r"(?im)^\s*copyright(?:\s|\(|$)", text):
        raise RuntimeError(f"MIT license text has no package-specific copyright line for shipped package {name}")


def license_text(
    package_dir: Path,
    metadata: dict,
    name: str,
    overrides: dict[str, dict] | None = None,
    used_overrides: set[str] | None = None,
) -> tuple[str, str]:
    declaration = declared_license(metadata)
    if not declaration:
        raise RuntimeError(f"Cannot determine a license text for shipped package {name} (no declaration)")
    if overrides is None:
        overrides = load_license_overrides()
    version = metadata.get("version")
    if not isinstance(version, str) or not version:
        raise RuntimeError(f"Shipped package has incomplete package.json: {package_dir}")
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
            license_pieces.append(f"[{path.name}]\n{text}")
    for path in notices:
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as exc:
            raise RuntimeError(f"Cannot read NOTICE for shipped package {name}: {path}") from exc
        if text:
            notice_pieces.append(f"[{path.name}]\n{text}")
    if not license_pieces:
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
    validate_license_text(declaration, text, name)
    return declaration or "See included license file", text


def asar_node_modules(pack: Path) -> set[str]:
    """Read only the ASAR header; no application payload is extracted."""
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
            elif path.startswith("dist/node_modules/"):
                relative = path[len("dist/node_modules/") :]
                parts = relative.split("/")
                if len(parts) >= 2 and parts[0].startswith("@") and len(parts) >= 3:
                    found.add("/".join(parts[:2]))
                elif parts:
                    found.add(parts[0])
    return {name for name in found if name != ".hermes-product"}


def package_identity(package_dir: Path, metadata: dict) -> str:
    name = metadata.get("name")
    version = metadata.get("version")
    if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
        raise RuntimeError(f"Shipped package has incomplete package.json: {package_dir}")
    return name


def collect_packages(source: Path, pack: Path) -> list[tuple[str, str, str, str, Path]]:
    desktop = source / "apps" / "desktop"
    desktop_meta = read_json(desktop / "package.json")
    overrides = load_license_overrides()
    used_overrides: set[str] = set()
    optional_names = optional_package_names(source)
    direct = {}
    for field, is_optional in (("dependencies", False), ("optionalDependencies", True), ("devDependencies", False)):
        values = desktop_meta.get(field, {})
        if isinstance(values, dict):
            for name in values:
                direct[name] = direct.get(name, True) and is_optional
    queue = [(desktop, name, optional) for name, optional in sorted(direct.items())]
    for name in sorted(asar_node_modules(pack)):
        queue.append((desktop, name, False))
    visited: set[Path] = set()
    packages = []
    while queue:
        parent, name, optional = queue.pop(0)
        package_dir = resolve_package(parent, name)
        if package_dir is None:
            if optional:
                continue
            raise RuntimeError(f"Installed dependency is missing: {name}")
        if package_dir in visited:
            continue
        visited.add(package_dir)
        metadata = read_json(package_dir / "package.json")
        package_name = package_identity(package_dir, metadata)
        if not is_workspace_package(source, package_dir):
            license_name, text = license_text(
                package_dir,
                metadata,
                package_name,
                overrides,
                used_overrides,
            )
            packages.append((package_name, metadata["version"], license_name, text, package_dir))
        fields = (("dependencies", False), ("optionalDependencies", True))
        if is_workspace_package(source, package_dir):
            fields += (("devDependencies", False),)
        for field, is_optional in fields:
            values = metadata.get(field, {})
            if isinstance(values, dict):
                dependency_optional = is_optional or package_name in optional_names or is_platform_package(package_name)
                queue.extend((package_dir, child, dependency_optional) for child in sorted(values))
    validate_unused_overrides(overrides, used_overrides)
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

    packages = collect_packages(source, pack)
    lines = [
        "THIRD-PARTY NOTICES",
        "=======================",
        "",
        "These notices cover a conservative superset of code that can ship in this Hermes Agent Light distribution.",
        "The set starts with desktop dependencies, optionalDependencies, and devDependencies, then follows installed dependencies recursively; reachable workspace packages also include their devDependencies.",
        f"Upstream repository: {UPSTREAM}",
        f"Upstream source ref: {source_ref}",
        f"Upstream commit: {commit}",
        "",
    ]
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
    third_party = pack / THIRD_PARTY_FILE
    third_party.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")

    unofficial = pack / UNOFFICIAL_FILE
    unofficial.write_text(
        "\n".join(
            [
                "Hermes Agent Light — unofficial distribution",
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
        "upstreamLicense": {"path": "LICENSE", "sha256": sha256(target_license)},
        "thirdParty": {"path": THIRD_PARTY_FILE, "sha256": sha256(third_party), "packages": len(packages)},
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
