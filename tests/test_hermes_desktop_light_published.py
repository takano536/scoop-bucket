"""Public verifier expectations derived from a published bucket commit."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("light_published", ROOT / "scripts/hermes-desktop-light.py")
assert spec is not None and spec.loader is not None
light = importlib.util.module_from_spec(spec)
spec.loader.exec_module(light)


class PublishedExpectationTests(unittest.TestCase):
    """The public verifier derives its expectations from the published bucket."""

    REPOSITORY = "takano536/scoop-bucket"

    def _publish_state(self, root, version, digest, commit, channel=None):
        """Write the manifest and pointer exactly as the publisher's writeback does."""
        channel = channel or light.CHANNELS["canary"]
        (root / "bucket").mkdir(parents=True, exist_ok=True)
        (root / light.RELEASE_POINTER).parent.mkdir(parents=True, exist_ok=True)
        desktop_version = version.split("-", 1)[0]
        pointer = light.release_pointer(
            version=version,
            digest=digest,
            commit=commit,
            desktop_version=desktop_version,
            desktop_tag="v0.21.6+canary.20261011T070142Z",
            desktop_feed_url=light.CANARY_FEED_URL,
            desktop_feed_etag='"etag"',
            desktop_feed_last_modified="Sun, 11 Oct 2026 08:00:00 GMT",
            desktop_artifact_url="https://example.invalid/HermesBundled.msixbundle",
            desktop_artifact_sha256="c" * 64,
            conditions_fingerprint="d" * 64,
            license_sha256="e" * 64,
            release_tag_value=light.release_tag(light.APP, version),
            artifact=light.artifact_name(light.APP, version),
            channel=channel,
        )
        data = light.manifest(
            version, self.REPOSITORY, digest, channel=channel, executable=pointer["executable"]
        )
        (root / "bucket" / f"{light.APP}.json").write_text(json.dumps(data, indent=4), encoding="utf-8")
        (root / light.RELEASE_POINTER).write_text(json.dumps(pointer, indent=2), encoding="utf-8")
        return data, pointer

    def test_expectations_follow_each_normal_publish(self):
        # The pinned verifier (PR #22) broke as soon as 26.1010 was superseded;
        # the same verifier must accept the next publish without edits.
        for version, digest, commit in (
            ("26.1010.7.26-alpha.dev.1-r1", "1" * 64, "2" * 40),
            ("26.1011.7.142-alpha.dev.1-r1", "3" * 64, "4" * 40),
        ):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as scratch:
                root = Path(scratch)
                data, _pointer = self._publish_state(root, version, digest, commit)
                self.assertEqual(
                    light.published_expectations(root, self.REPOSITORY),
                    {
                        "version": version,
                        "sha256": digest,
                        "url": data["architecture"]["64bit"]["url"],
                        "upstream_commit": commit,
                    },
                )

    def test_manifest_and_pointer_disagreement_is_rejected(self):
        mutations = {
            "manifest version": lambda data, pointer: data.update(version="26.1011.7.142-alpha.dev.1-r2"),
            "manifest hash": lambda data, pointer: data["architecture"]["64bit"].update(hash="9" * 64),
            "manifest url": lambda data, pointer: data["architecture"]["64bit"].update(url="https://example.invalid/x.zip"),
            "manifest shortcut": lambda data, pointer: data.update(shortcuts=[["other.exe", "Other"]]),
            "pointer release tag": lambda data, pointer: pointer.update(releaseTag="hermes-desktop-light/v0"),
            "pointer artifact": lambda data, pointer: pointer.update(artifact="other.zip"),
            "pointer upstream commit": lambda data, pointer: pointer.update(commit="main"),
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name), tempfile.TemporaryDirectory() as scratch:
                root = Path(scratch)
                data, pointer = self._publish_state(root, "26.1011.7.142-alpha.dev.1-r1", "3" * 64, "4" * 40)
                mutate(data, pointer)
                (root / "bucket" / f"{light.APP}.json").write_text(json.dumps(data), encoding="utf-8")
                (root / light.RELEASE_POINTER).write_text(json.dumps(pointer), encoding="utf-8")
                with self.assertRaises(ValueError):
                    light.published_expectations(root, self.REPOSITORY)


    def test_expectations_follow_a_stable_channel_publish(self):
        for version, digest, commit in (
            ("2026.6864.2132.0-r1", "5" * 64, "6" * 40),
        ):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as scratch:
                root = Path(scratch)
                data, pointer = self._publish_state(
                    root, version, digest, commit, light.CHANNELS["stable"]
                )
                self.assertEqual(pointer["upstreamChannel"], "stable")
                self.assertEqual(
                    light.published_expectations(root, self.REPOSITORY),
                    {
                        "version": version,
                        "sha256": digest,
                        "url": data["architecture"]["64bit"]["url"],
                        "upstream_commit": commit,
                    },
                )


if __name__ == "__main__":
    unittest.main()
