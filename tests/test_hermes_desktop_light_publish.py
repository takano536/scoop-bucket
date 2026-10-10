"""Publisher-facing manifest and provenance contract tests."""
import hashlib
import importlib.util
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
import zipfile
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
PRODUCER = ROOT / "scripts/build-hermes-desktop-light.ps1"
spec = importlib.util.spec_from_file_location("light_publish", ROOT / "scripts/hermes-desktop-light.py")
assert spec is not None and spec.loader is not None
light = importlib.util.module_from_spec(spec)
spec.loader.exec_module(light)


class _BytesResponse:
    def __init__(self, payload):
        self.payload = payload
        self.read_once = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        if self.read_once:
            return b""
        self.read_once = True
        return self.payload


def _producer_record(*, version, commit, tag, desktop_version, artifact, digest, conditions, license_digest):
    return {
        "schema": 2,
        "upstream": light.UPSTREAM,
        "sourceRef": commit,
        "commit": commit,
        "desktopTag": tag,
        "upstreamChannel": "canary",
        "desktopVersion": desktop_version,
        "desktopFeedUrl": light.DESKTOP_FEED_URL,
        "desktopFeedEtag": '"feed-etag"',
        "desktopFeedLastModified": "Fri, 09 Oct 2026 08:04:40 GMT",
        "desktopArtifactUrl": "https://example.invalid/HermesBundled.msixbundle",
        "desktopArtifactSha256": "c" * 64,
        "version": version,
        "preview": False,
        "development": True,
        "channel": "desktop-release",
        "distribution": "unofficial-light",
        "artifact": artifact,
        "sha256": digest,
        "payload": "light",
        "updateMechanism": "external",
        "executable": "hermes-light-canary.exe",
        "smoke": "two native launches; renderer loaded; localStorage retained",
        "nativeChecks": {},
        "notices": {},
        "signing": "unsigned unofficial build",
        "licenseSha256": license_digest,
        "conditionsFingerprint": conditions,
        "bucketCommit": "f" * 40,
        "run": "https://github.com/example/bucket/actions/runs/1",
    }


class PublishContractTests(unittest.TestCase):
    def setUp(self):
        self.version = "26.1009.7.410-alpha.dev.1-r1"
        self.digest = "a" * 64
        self.commit = "b" * 40
        self.desktop_digest = "c" * 64
        self.conditions = "d" * 64
        self.license = "e" * 64

    def _fixture(self, root):
        output = root / "output"
        output.mkdir()
        acceptance = root / "acceptance"
        acceptance.mkdir()
        tag = "v0.21.6+canary.20261009T070410Z"
        desktop_version = "26.1009.7.410"
        artifact = output / light.artifact_name(light.APP, self.version)
        entries = {
            "hermes-light-canary.exe": b"fixture executable",
            "resources/app.asar": b"fixture asar",
            "resources/install-stamp.json": json.dumps(
                {"commit": self.commit, "payload": "light", "updateMechanism": "external"}
            ).encode(),
            "LICENSE": b"MIT License\nCopyright (c) 2025 Nous Research\n",
            "LICENSE.electron.txt": b"Electron license\n",
            "LICENSES.chromium.html": b"<html>Chromium</html>\n",
            "THIRD-PARTY-NOTICES.txt": b"fixture third-party notice\n",
            "UNOFFICIAL-BUILD.txt": b"Unofficial build\n",
        }
        with zipfile.ZipFile(artifact, "w") as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
        notices = {
            key: {"path": path, "sha256": hashlib.sha256(entries[path]).hexdigest()}
            for key, path in {
                "upstreamLicense": "LICENSE",
                "thirdParty": "THIRD-PARTY-NOTICES.txt",
                "unofficial": "UNOFFICIAL-BUILD.txt",
            }.items()
        }
        notices["thirdParty"]["packages"] = 1
        notices["audit"] = {"status": "complete", "limitations": [], "unresolved": []}
        record = _producer_record(
            version=self.version,
            commit=self.commit,
            tag=tag,
            desktop_version=desktop_version,
            artifact=artifact.name,
            digest=hashlib.sha256(artifact.read_bytes()).hexdigest(),
            conditions=self.conditions,
            license_digest=self.license,
        )
        record["notices"] = notices
        (output / "provenance.json").write_text(json.dumps(record), encoding="utf-8")
        (acceptance / "acceptance.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "sourceRef": self.commit,
                    "commit": self.commit,
                    "bucketPackageVersion": self.version,
                    "artifact": artifact.name,
                    "artifactSha256": record["sha256"],
                }
            ),
            encoding="utf-8",
        )
        live = {
            "desktopVersion": desktop_version,
            "desktopTag": tag,
            "desktopCommit": self.commit,
            "desktopFeedUrl": light.DESKTOP_FEED_URL,
            "desktopFeedEtag": record["desktopFeedEtag"],
            "desktopFeedLastModified": record["desktopFeedLastModified"],
            "desktopArtifactUrl": record["desktopArtifactUrl"],
            "desktopArtifactSha256": record["desktopArtifactSha256"],
            "desktopSourceUrl": light.DESKTOP_FEED_URL,
        }
        return record, live, artifact

    def _publish_environment(self, record, root):
        return {
            "PACKAGE_VERSION": record["version"],
            "SOURCE_REF": record["commit"],
            "UPSTREAM_TAG": record["desktopTag"],
            "DESKTOP_VERSION": record["desktopVersion"],
            "DESKTOP_FEED_URL": record["desktopFeedUrl"],
            "CONDITIONS_FINGERPRINT": record["conditionsFingerprint"],
            "LICENSE_SHA256": record["licenseSha256"],
            "GITHUB_REPOSITORY": "example/bucket",
            "ACCEPTANCE_EVIDENCE": str(root / "acceptance" / "acceptance.json"),
        }

    def test_producer_emits_exact_consumer_provenance_shape(self):
        source = PRODUCER.read_text(encoding="utf-8")
        receipt_body = source.split("$receipt = @{", 1)[1].split("}\n$receipt |", 1)[0]
        producer_keys = set(re.findall(r"(?m)^\s+([A-Za-z]\w*)\s*=", receipt_body))
        record = _producer_record(
            version=self.version,
            commit=self.commit,
            tag="v0.21.6+canary.20261009T070410Z",
            desktop_version="26.1009.7.410",
            artifact="hermes-desktop-light-26.1009.7.410-alpha.dev.1-r1-windows-x64.zip",
            digest=self.digest,
            conditions=self.conditions,
            license_digest=self.license,
        )
        self.assertEqual(set(record), producer_keys)
        self.assertIn("desktopTag", producer_keys)
        self.assertNotIn("upstreamTag", producer_keys)

    def test_valid_provenance_reaches_release_mutation_after_prevalidation(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            record, live, artifact = self._fixture(root)
            release_tag = light.release_tag(light.APP, self.version)
            release_rows = Mock(return_value=[{"tag_name": release_tag, "id": 7, "assets": []}])
            api = Mock(side_effect=[{"assets": []}, {"draft": False, "prerelease": True}])
            gh = Mock(return_value="")
            writeback = Mock()
            response = _BytesResponse(artifact.read_bytes())
            previous = Path.cwd()
            os.chdir(root)
            try:
                with patch.dict(os.environ, self._publish_environment(record, root), clear=False), \
                     patch.object(light, "_desktop_feed", return_value={}), \
                     patch.object(light, "_desktop_provenance", return_value=live), \
                     patch.object(light, "_release_rows", release_rows), \
                     patch.object(light, "api", api), \
                     patch.object(light, "gh", gh), \
                     patch.object(light, "_writeback", writeback), \
                     patch("urllib.request.urlopen", return_value=response):
                    light._publish_desktop()
            finally:
                os.chdir(previous)
            release_rows.assert_called_once_with("example/bucket")
            gh.assert_any_call(
                "release",
                "edit",
                release_tag,
                "--repo",
                "example/bucket",
                "--draft=false",
                "--prerelease=true",
                "--latest=false",
            )
            writeback.assert_called_once()

    def test_bound_provenance_mismatch_rejects_before_release_or_writeback(self):
        mismatches = {
            "tag": lambda record: record.update(desktopTag="v0.21.6+canary.20261009T080410Z"),
            "desktop version": lambda record: record.update(desktopVersion="26.1009.7.411"),
            "commit": lambda record: record.update(commit="0" * 40),
            "source ref": lambda record: record.update(sourceRef="1" * 40),
            "fingerprint": lambda record: record.update(conditionsFingerprint="1" * 64),
            "license digest": lambda record: record.update(licenseSha256="2" * 64),
            "artifact name": lambda record: record.update(artifact="other.zip"),
            "payload": lambda record: record.update(payload="full"),
        }
        for name, mutate in mismatches.items():
            with self.subTest(field=name), tempfile.TemporaryDirectory() as scratch:
                root = Path(scratch)
                record, live, _artifact = self._fixture(root)
                environment = self._publish_environment(record, root)
                mutate(record)
                (root / "output" / "provenance.json").write_text(json.dumps(record), encoding="utf-8")
                release_rows = Mock()
                api = Mock()
                gh = Mock()
                writeback = Mock()
                previous = Path.cwd()
                os.chdir(root)
                try:
                    with patch.dict(os.environ, environment, clear=False), \
                         patch.object(light, "_desktop_feed", return_value={}), \
                         patch.object(light, "_desktop_provenance", return_value=live), \
                         patch.object(light, "_release_rows", release_rows), \
                         patch.object(light, "api", api), \
                         patch.object(light, "gh", gh), \
                         patch.object(light, "_writeback", writeback):
                        with self.assertRaises(ValueError):
                            light._publish_desktop()
                finally:
                    os.chdir(previous)
                release_rows.assert_not_called()
                api.assert_not_called()
                gh.assert_not_called()
                writeback.assert_not_called()
                self.assertFalse((root / "output" / f"{light.APP}.json").exists())

    def test_manifest_points_to_immutable_unofficial_release_and_pointer(self):
        data = light.manifest(self.version, "takano536/scoop-bucket", self.digest)
        self.assertEqual(data["architecture"]["64bit"]["hash"], self.digest)
        self.assertIn("hermes-desktop-light%2Fv26.1009.7.410-alpha.dev.1-r1", data["architecture"]["64bit"]["url"])
        self.assertEqual(data["shortcuts"], [["hermes-light-canary.exe", "Hermes Desktop Light (Unofficial)"]])
        self.assertIn("hermes-desktop-light-release.json", data["checkver"]["url"])
        self.assertIn("officially published Hermes Desktop canary", data["notes"])

    def test_release_pointer_records_both_upstream_and_bucket_identity(self):
        pointer = light.release_pointer(
            version=self.version,
            digest=self.digest,
            commit=self.commit,
            desktop_version="26.1009.7.410",
            desktop_tag="v0.21.6+canary.20261009T070410Z",
            desktop_feed_url=light.DESKTOP_FEED_URL,
            desktop_feed_etag='"feed"',
            desktop_feed_last_modified="Fri, 09 Oct 2026 08:04:40 GMT",
            desktop_artifact_url="https://example.invalid/HermesBundled.msixbundle",
            desktop_artifact_sha256=self.desktop_digest,
            conditions_fingerprint=self.conditions,
            license_sha256=self.license,
            release_tag_value=f"{light.APP}/v{self.version}",
            artifact=f"{light.APP}-{self.version}-windows-x64.zip",
        )
        self.assertEqual(pointer["distribution"], "unofficial-light")
        self.assertEqual(pointer["upstreamChannel"], "canary")
        self.assertEqual(pointer["desktopVersion"], "26.1009.7.410")
        self.assertEqual(pointer["commit"], self.commit)
        self.assertEqual(pointer["desktopArtifactSha256"], self.desktop_digest)
        self.assertEqual(pointer["conditionsFingerprint"], self.conditions)

    def test_pointer_rejects_untrusted_digest_or_version(self):
        with self.assertRaises(ValueError):
            light.release_pointer(
                version="0.0.0-alpha.dev.1-r1",
                digest=self.digest,
                commit=self.commit,
                desktop_version="26.1009.7.410",
                desktop_tag="v0.21.6+canary.20261009T070410Z",
                desktop_feed_url=light.DESKTOP_FEED_URL,
                desktop_feed_etag="",
                desktop_feed_last_modified="",
                desktop_artifact_url="https://example.invalid/a",
                desktop_artifact_sha256=self.desktop_digest,
                conditions_fingerprint=self.conditions,
                license_sha256=self.license,
                release_tag_value="tag",
                artifact="artifact.zip",
            )


if __name__ == "__main__":
    unittest.main()
