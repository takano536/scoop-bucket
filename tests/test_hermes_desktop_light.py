import importlib.util
import json
import os
from pathlib import Path
import subprocess
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

    def http_responses(self, *, handoff_commit=None):
        version = self.fixture.provenance["desktopVersion"]
        tag = self.fixture.provenance["desktopTag"]
        commit = handoff_commit or self.fixture.provenance["desktopCommit"]
        artifact_name = f"HermesBundled-{version}-win.msixbundle"
        artifact_url = self.fixture.provenance["desktopArtifactUrl"]
        archive_base = f"{light.DESKTOP_PUBLIC_BASE}/releases/tag/{light.quote(tag, safe='')}"
        handoff = {
            "schema": 1,
            "name": "windows-universal",
            "tag": tag,
            "commit": commit,
            "files": [{"path": artifact_name, "sha256": "c" * 64, "size": 123}],
        }
        metadata = {
            "commit": self.fixture.provenance["desktopCommit"],
            "tag": tag,
            "platform": "windows",
            "arch": "x64",
            "version": version,
            "executableVersion": version,
        }
        feed_xml = (
            f'<AppInstaller Version="{version}"><MainBundle Version="{version}" '
            f'Uri="{artifact_url}" /></AppInstaller>'
        ).encode()

        def fake_http(url, method="GET"):
            if url == light.DESKTOP_FEED_URL:
                return feed_xml, {
                    "etag": '"feed-etag"',
                    "last-modified": "Fri, 09 Oct 2026 08:04:40 GMT",
                }
            if url == artifact_url and method == "HEAD":
                return b"", {
                    "content-length": "123",
                    "etag": '"artifact-etag"',
                    "last-modified": "Fri, 09 Oct 2026 08:04:40 GMT",
                }
            if url == f"{archive_base}/handoff-windows-universal.json":
                return json.dumps(handoff).encode(), {"etag": '"handoff-etag"'}
            if url == f"{archive_base}/{light.quote(artifact_name, safe='')}" and method == "HEAD":
                return b"", {"content-length": "123", "etag": '"artifact-etag"'}
            if url == f"{archive_base}/metadata-windows-x64.json":
                return json.dumps(metadata).encode(), {"etag": '"metadata-etag"'}
            raise AssertionError(f"unexpected HTTP request: {method} {url}")

        return fake_http

    def test_only_main_advanced_is_not_a_new_desktop_release(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            os.chdir(directory)
            try:
                Path("metadata").mkdir()
                Path(light.RELEASE_POINTER).write_text(json.dumps(self.pointer()), encoding="utf-8")
                gh_calls = []
                api_calls = []
                main_head = "f" * 40
                newer_tag = "v0.21.6+canary.20261009T080410Z"

                def fake_gh(*args):
                    gh_calls.append(args)
                    return json.dumps([[
                        {"name": self.fixture.provenance["desktopTag"], "commit": {"sha": self.fixture.provenance["desktopCommit"]}},
                        {"name": newer_tag, "commit": {"sha": main_head}},
                    ]])

                def fake_api(endpoint):
                    api_calls.append(endpoint)
                    if "/git/ref/tags/" in endpoint:
                        return {"object": {"type": "tag", "sha": "b" * 40}}
                    if "/git/tags/" in endpoint:
                        return {"object": {"type": "commit", "sha": self.fixture.provenance["desktopCommit"]}}
                    raise AssertionError(f"unexpected GitHub API request: {endpoint}")

                with patch.dict(
                    os.environ,
                    {"GITHUB_EVENT_NAME": "schedule", "BUILD_REVISION": "1", "REVISION_EXPLICIT": "false"},
                    clear=False,
                ), patch.object(light, "_http", side_effect=self.http_responses()), \
                     patch.object(light, "gh", side_effect=fake_gh), \
                     patch.object(light, "api", side_effect=fake_api), \
                     patch.object(light, "conditions_fingerprint", return_value="d" * 64), \
                     patch.object(light, "supports_light") as supports, \
                     patch.object(light, "output", self.result):
                    light.plan()
                self.result.assert_called_once_with(build="false", channel="desktop-release", status="idempotent")
                supports.assert_not_called()
                self.assertTrue(gh_calls)
                self.assertTrue(api_calls)
                calls = " ".join(" ".join(call) for call in gh_calls) + " " + " ".join(api_calls)
                self.assertNotIn("refs/heads/main", calls)
                self.assertNotIn("/heads/", calls)
                self.assertNotIn("/commits/", calls)
            finally:
                os.chdir(previous)

    def test_new_published_desktop_build_plans_exact_source_commit(self):
        supports = self.run_plan(pointer=None)
        values = self.result.call_args.kwargs
        self.assertEqual(values["build"], "true")
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
        def assert_not_unsupported():
            self.assertFalse(
                any(call.kwargs.get("status") == "unsupported" for call in self.result.call_args_list)
            )

        with patch.object(light, "_desktop_feed", side_effect=light.ProvenanceError("feed unavailable")), \
             patch.object(light, "output", self.result):
            self.assertEqual(light.main(["plan"]), 2)
        self.result.assert_not_called()

        self.result.reset_mock()
        api_failure = subprocess.CalledProcessError(1, ["gh", "api"], stderr="HTTP 500")
        with patch.object(light, "_desktop_feed", return_value=self.fixture.feed), \
             patch.object(light, "_repository_tags", return_value=[{"name": self.fixture.provenance["desktopTag"]}]), \
             patch.object(light, "gh", side_effect=api_failure), \
             patch.object(light, "output", self.result):
            self.assertEqual(light.main(["plan"]), 2)
        self.result.assert_not_called()
        assert_not_unsupported()

        self.result.reset_mock()
        with patch.object(light, "_desktop_feed", return_value=self.fixture.feed), \
             patch.object(light, "_repository_tags", return_value=[]), \
             patch.object(light, "output", self.result):
            self.assertEqual(light.main(["plan"]), 2)
        self.result.assert_not_called()
        assert_not_unsupported()

        self.result.reset_mock()
        with patch.object(light, "_desktop_feed", return_value=self.fixture.feed), \
             patch.object(light, "_repository_tags", return_value=[{"name": self.fixture.provenance["desktopTag"]}]), \
             patch.object(
                 light,
                 "api",
                 side_effect=[
                     {"object": {"type": "tag", "sha": "b" * 40}},
                     {"object": {"type": "commit", "sha": self.fixture.provenance["desktopCommit"]}},
                 ],
             ), patch.object(light, "_http", side_effect=self.http_responses(handoff_commit="e" * 40)), \
             patch.object(light, "output", self.result):
            self.assertEqual(light.main(["plan"]), 2)
        self.result.assert_not_called()
        assert_not_unsupported()

        self.result.reset_mock()
        with patch.object(light, "_current_version", return_value=None), \
             patch.object(light, "_desktop_feed", return_value=self.fixture.feed), \
             patch.object(light, "_desktop_provenance", return_value=self.fixture.provenance), \
             patch.object(light, "supports_light", return_value=False), \
             patch.object(light, "output", self.result):
            self.assertEqual(light.main(["plan"]), 0)
        self.assertEqual(self.result.call_args.kwargs["status"], "unsupported")

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
