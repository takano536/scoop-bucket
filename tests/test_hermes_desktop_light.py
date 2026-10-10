import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/hermes-desktop-light.py"
spec = importlib.util.spec_from_file_location("light", SCRIPT)
assert spec is not None and spec.loader is not None
light = importlib.util.module_from_spec(spec)
spec.loader.exec_module(light)


class FeedFixtures:
    def __init__(self, *, version="26.1009.7.410", tag="v0.21.6+canary.20261009T070410Z", commit="a" * 40):
        self.feed = {
            "desktopVersion": version,
            "desktopFeedUrl": light.DESKTOP_FEED_URL,
            "desktopFeedEtag": '"feed-etag"',
            "desktopFeedLastModified": "Fri, 09 Oct 2026 08:04:40 GMT",
            "desktopArtifactUrl": f"{light.DESKTOP_PUBLIC_BASE}/releases/win32/canary/HermesBundled-{version}-win.msixbundle",
            "desktopArtifactSize": 123,
            "desktopArtifactEtag": '"artifact-etag"',
            "desktopArtifactLastModified": "Fri, 09 Oct 2026 08:04:40 GMT",
        }
        self.provenance = {
            **self.feed,
            "desktopTag": tag,
            "desktopCommit": commit,
            "desktopTagObject": "b" * 40,
            "desktopArtifactSha256": "c" * 64,
            "desktopHandoffUrl": f"{light.DESKTOP_PUBLIC_BASE}/releases/tag/{tag}/handoff-windows-universal.json",
        }


class VersionTests(unittest.TestCase):
    def test_desktop_version_and_revision_identity(self):
        version = "26.1009.7.410-alpha.dev.1-r1"
        self.assertEqual(light.package_version("26.1009.7.410", "1"), version)
        self.assertEqual(
            light.release_tag(light.APP, version),
            f"{light.APP}/v{version}",
        )
        self.assertEqual(
            light.artifact_name(light.APP, version),
            f"{light.APP}-{version}-windows-x64.zip",
        )

    def test_normal_scoop_ordering_moves_legacy_to_desktop_release(self):
        legacy = "0.0.0-alpha.dev.1-r1"
        first = "26.1009.7.410-alpha.dev.1-r1"
        second = "26.1009.7.410-alpha.dev.1-r2"
        future = "26.1010.1.100-r1"
        self.assertLess(light.distribution_version_key(legacy), light.distribution_version_key(first))
        self.assertLess(light.distribution_version_key(first), light.distribution_version_key(second))
        self.assertLess(light.distribution_version_key(second), light.distribution_version_key(future))

    def test_invalid_product_versions_fail_closed(self):
        for value in (
            "26.1009.7",
            "26.01009.7.410",
            "26.1009.7.410-alpha.dev.0-r1",
            "26.1009.7.410-alpha.dev.1-r01",
        ):
            with self.assertRaises(ValueError):
                light.package_version(value.split("-", 1)[0], "1") if "alpha" not in value else light.light_version_key(value)


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FeedFixtures()
        self.result = Mock()

    def run_plan(self, *, event="schedule", pointer=None, current=None, supported=True, revision="1", explicit="false"):
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            os.chdir(directory)
            try:
                if pointer is not None:
                    Path("metadata").mkdir()
                    Path(light.RELEASE_POINTER).write_text(json.dumps(pointer), encoding="utf-8")
                if current is not None:
                    Path("bucket").mkdir()
                    Path("bucket/hermes-desktop-light.json").write_text(json.dumps({"version": current}), encoding="utf-8")
                env = {
                    "GITHUB_EVENT_NAME": event,
                    "BUILD_REVISION": revision,
                    "REVISION_EXPLICIT": explicit,
                }
                with patch.dict(os.environ, env, clear=False), \
                     patch.object(light, "_desktop_feed", return_value=self.fixture.feed), \
                     patch.object(light, "_desktop_provenance", return_value=self.fixture.provenance), \
                     patch.object(light, "supports_light", return_value=supported) as supports, \
                     patch.object(light, "license_sha", return_value="e" * 64), \
                     patch.object(light, "conditions_fingerprint", return_value="d" * 64), \
                     patch.object(light, "output", self.result):
                    light.plan()
                return supports
            finally:
                os.chdir(previous)

    def pointer(self, *, fingerprint="d" * 64, version="26.1009.7.410-alpha.dev.1-r1"):
        return {
            "desktopTag": self.fixture.provenance["desktopTag"],
            "commit": self.fixture.provenance["desktopCommit"],
            "version": version,
            "conditionsFingerprint": fingerprint,
        }

    def test_only_main_advanced_is_not_a_new_desktop_release(self):
        supports = self.run_plan(pointer=self.pointer())
        self.result.assert_called_once_with(build="false", channel="desktop-release", status="idempotent")
        supports.assert_not_called()

    def test_new_published_desktop_build_plans_exact_source_commit(self):
        supports = self.run_plan(pointer=None)
        values = self.result.call_args.kwargs
        self.assertTrue(values.pop("build"))
        self.assertEqual(values["status"], "new-desktop-release")
        self.assertEqual(values["ref"], self.fixture.provenance["desktopCommit"])
        self.assertEqual(values["upstream_tag"], self.fixture.provenance["desktopTag"])
        self.assertEqual(values["desktop_version"], self.fixture.provenance["desktopVersion"])
        supports.assert_called_once_with(self.fixture.provenance["desktopCommit"])

    def test_unsupported_light_source_skips_without_manifest_change(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            os.chdir(directory)
            try:
                Path("bucket").mkdir()
                target = Path("bucket/hermes-desktop-light.json")
                original = {"version": "0.0.0-alpha.dev.1-r1"}
                target.write_text(json.dumps(original), encoding="utf-8")
                with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "schedule", "BUILD_REVISION": "1", "REVISION_EXPLICIT": "false"}, clear=False), \
                     patch.object(light, "_desktop_feed", return_value=self.fixture.feed), \
                     patch.object(light, "_desktop_provenance", return_value=self.fixture.provenance), \
                     patch.object(light, "supports_light", return_value=False), \
                     patch.object(light, "output", self.result):
                    light.plan()
                self.result.assert_called_once()
                self.assertEqual(self.result.call_args.kwargs["status"], "unsupported")
                self.assertEqual(json.loads(target.read_text(encoding="utf-8")), original)
            finally:
                os.chdir(previous)

    def test_same_published_desktop_build_is_idempotent(self):
        supports = self.run_plan(pointer=self.pointer(), current="26.1009.7.410-alpha.dev.1-r1")
        self.result.assert_called_once_with(build="false", channel="desktop-release", status="idempotent")
        supports.assert_not_called()

    def test_api_or_unknown_provenance_is_not_an_unsupported_skip(self):
        with patch.object(light, "_desktop_feed", side_effect=light.ProvenanceError("feed unavailable")), \
             patch.object(light, "output", self.result):
            with self.assertRaises(light.ProvenanceError):
                light.plan()
        self.result.assert_not_called()

    def test_revision_two_requires_explicit_dispatch_for_same_release(self):
        self.run_plan(pointer=self.pointer(), revision="2", explicit="false")
        self.result.assert_called_once_with(build="false", channel="desktop-release", status="revision-required")


class MappingTests(unittest.TestCase):
    def test_canary_product_version_maps_to_one_annotated_tag(self):
        tags = [{"name": "v0.21.6+canary.20261009T070410Z"}]
        with patch.object(light, "_repository_tags", return_value=tags):
            self.assertEqual(light._tag_for_product_version("26.1009.7.410"), tags[0]["name"])

    def test_ambiguous_or_missing_tag_is_a_provenance_failure(self):
        for tags in ([], [{"name": "v0.21.6+canary.20261009T070410Z"}, {"name": "v0.21.5+canary.20261009T070410Z"}]):
            with self.subTest(tags=tags), patch.object(light, "_repository_tags", return_value=tags):
                with self.assertRaises(light.ProvenanceError):
                    light._tag_for_product_version("26.1009.7.410")


if __name__ == "__main__":
    unittest.main()
