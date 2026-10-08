#!/usr/bin/env python3
"""Generate the license and provenance files shipped in Hermes Desktop Light."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
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
        if not isinstance(copyright_line, str) or not re.search(
            r"(?i)\bcopyright\b", copyright_line
        ):
            raise RuntimeError(f"License override has invalid copyright line: {key}")
        if not isinstance(evidence, dict):
            raise RuntimeError(f"License override has no evidence object: {key}")
        kind = evidence.get("kind")
        if kind not in {"attribution", "license"}:
            raise RuntimeError(f"License override evidence kind is invalid: {key}")
        url = evidence.get("url")
        digest = evidence.get("sha256")
        path = evidence.get("path")
        retrieval = evidence.get("retrieval")
        if not isinstance(url, str) or not re.fullmatch(
            r"https://raw\.githubusercontent\.com/[^/]+/[^/]+/[0-9a-f]{40}/.+",
            url,
        ):
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
        if not isinstance(note, str) or not note.strip():
            raise RuntimeError(f"License override has no note: {key}")
    return data


def validate_unused_overrides(overrides: dict[str, dict], used: set[str]) -> None:
    unused = sorted(set(overrides) - used)
    if unused:
        raise RuntimeError(f"Unused license override entries: {', '.join(unused)}")


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
) -> None:
    identifiers = spdx_identifiers(declaration) or []
    if "MPL-2.0" in identifiers:
        missing = [marker for marker in MPL_REQUIRED_MARKERS if marker not in text]
        if missing:
            raise RuntimeError(f"Incomplete MPL-2.0 license text for shipped package {name}")
    if "MIT" in identifiers:
        missing = [marker for marker in MIT_REQUIRED_MARKERS if marker not in text]
        if missing:
            raise RuntimeError(f"Incomplete MIT license text for shipped package {name}")
        if has_placeholder_copyright(text):
            raise RuntimeError(f"MIT license text has placeholder copyright for shipped package {name}")
        if not package_supplied and not has_package_copyright(text):
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


def bundle_module_graph(source: Path) -> dict:
    """Read Vite source maps and esbuild metafiles emitted by the controlled build."""
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
    packages: dict[tuple[str, Path], dict] = {}
    module_count = 0
    for map_file in map_files:
        try:
            metadata = json.loads(map_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot read bundle source map: {map_file}") from exc
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
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot read bundle metafile: {metafile}") from exc
        inputs = metadata.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for input_name in inputs:
            if not isinstance(input_name, str):
                continue
            package = package_at_path(source_map_path(metafile, input_name))
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
        raise RuntimeError("Cannot obtain bundled module graph: no source maps or esbuild metafiles")
    if not packages:
        raise RuntimeError("Cannot obtain bundled module graph: no package modules found")
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
        "moduleCount": module_count,
        "packages": sorted(packages.values(), key=lambda item: (item["name"].lower(), item["path"].lower())),
    }


def bundle_package_origins(bundle_graph: dict) -> dict[str, set[str]]:
    origins: dict[str, set[str]] = {}
    for entry in bundle_graph.get("packages", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            continue
        origins.setdefault(entry["name"], set()).add("bundle-map")
    return origins
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
    optional_names = optional_package_names(source)
    asar_names = asar_node_modules(pack)
    unpacked_names = unpacked_node_modules(pack)
    bundle_graph = bundle_graph or {"packages": []}
    queue: list[tuple[Path, str, bool, Path | None, str | None]] = []
    origins: dict[str, set[str]] = {}

    def enqueue(parent: Path, name: str, optional: bool, hint: Path | None, origin: str | None) -> None:
        queue.append((parent, name, optional, hint, origin))
        if origin is not None:
            origins.setdefault(name, set()).add(origin)

    for name in sorted(asar_names):
        enqueue(desktop, name, False, None, "asar")
    for name in sorted(unpacked_names):
        enqueue(desktop, name, False, None, "unpacked")
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
        enqueue(desktop, name, False, package_hint, "bundle-map")
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
        parent, name, optional, hint, origin = queue.pop(0)
        package_dir = hint if hint is not None else resolve_package(parent, name)
        if package_dir is None:
            if optional:
                continue
            raise RuntimeError(f"Installed dependency is missing: {name}")
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
                license_failures.append(f"{package_name}@{metadata['version']}: {exc}")
            else:
                packages.append((package_name, metadata["version"], license_name, text, package_dir))
        fields = (("dependencies", False), ("optionalDependencies", True))
        for field, is_optional in fields:
            values = metadata.get(field, {})
            if isinstance(values, dict):
                dependency_optional = is_optional or package_name in optional_names or is_platform_package(package_name)
                for child in sorted(values):
                    enqueue(package_dir, child, dependency_optional, None, None)
    try:
        validate_unused_overrides(overrides, used_overrides)
    except RuntimeError as exc:
        license_failures.append(str(exc))
    if license_failures:
        details = "\n".join(f"- {failure}" for failure in license_failures)
        raise RuntimeError(f"License validation failed for shipped packages:\n{details}")
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

    bundle_graph = bundle_module_graph(source)
    graph_target = pack / "resources" / BUNDLE_GRAPH_FILE
    graph_target.parent.mkdir(parents=True, exist_ok=True)
    graph_target.write_text(
        json.dumps(bundle_graph, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    inventory: dict = {}
    packages = collect_packages(source, pack, bundle_graph, inventory)
    lines = [
        "THIRD-PARTY NOTICES",
        "=======================",
        "",
        "These notices cover code present in the Hermes Desktop Light win-unpacked payload.",
        "The inventory is the union of package paths in the app.asar header, physical node_modules under resources/app.asar.unpacked/resources, and package modules identified in the emitted Vite source maps and esbuild metafiles.",
        "DevDependencies and build tooling are included only when the bundle graph proves that their modules shipped; packages listed only in package.json are not included.",
        f"Inventory source counts (unique package names): asar={inventory['asar']}; unpacked={inventory['unpacked']}; bundle-map={inventory['bundleMap']}.",
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
            },
        },
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
