"""Publisher-facing manifest and provenance contract tests."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("light_publish", ROOT / "scripts/hermes-desktop-light.py")
assert spec is not None and spec.loader is not None
light = importlib.util.module_from_spec(spec)
spec.loader.exec_module(light)


class PublishContractTests(unittest.TestCase):
    def setUp(self):
        self.version = "26.1009.7.410-alpha.dev.1-r1"
        self.digest = "a" * 64
        self.commit = "b" * 40
        self.desktop_digest = "c" * 64
        self.conditions = "d" * 64
        self.license = "e" * 64

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
