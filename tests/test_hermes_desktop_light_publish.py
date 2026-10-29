"""Publisher-facing manifest and provenance contract tests."""
import hashlib
import importlib.util
import io
import json
import os
from contextlib import redirect_stderr
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

CANARY = light.CHANNELS["canary"]

# GitHub REST "Create a release" / "Update a release" request bodies. The
# endpoints reject wrongly typed fields with HTTP 422 (for example
# `For 'properties/make_latest', false is not a string.`).
RELEASE_WRITE_FIELDS = {
    "tag_name": str,
    "target_commitish": str,
    "name": str,
    "body": str,
    "draft": bool,
    "prerelease": bool,
    "make_latest": ("true", "false", "legacy"),
}


def _gh_api_request(argv, stdin):
    """Return (endpoint, method, JSON body) exactly as `gh api` would send it.

    Mirrors the typing rules documented by `gh api --help`: `--field/-F`
    converts literal true/false/null and integers to JSON types (and implies
    POST), `--raw-field/-f` sends strings, `--input -` sends stdin verbatim.
    """
    assert argv[:2] == ["gh", "api"], argv
    endpoint, args = argv[2], argv[3:]
    method, body, has_fields = None, {}, False
    index = 0
    while index < len(args):
        flag, value = args[index], args[index + 1] if index + 1 < len(args) else None
        if flag in ("--method", "-X"):
            method = value
        elif flag == "--input":
            assert value == "-", "request bodies must come from stdin"
            body = json.loads(stdin)
        elif flag in ("--field", "-F", "--raw-field", "-f"):
            has_fields = True
            key, raw = value.split("=", 1)
            if flag in ("--field", "-F"):
                assert not raw.startswith("@"), "typed field would read a file"
                if raw in ("true", "false"):
                    raw = raw == "true"
                elif raw == "null":
                    raw = None
                elif re.fullmatch(r"-?\d+", raw):
                    raw = int(raw)
            body[key] = raw
        else:
            raise AssertionError(f"unexpected gh api argument: {flag}")
        index += 2
    return endpoint, method or ("POST" if has_fields else "GET"), body


def _assert_release_write_body(test, body, *, create):
    if create:
        test.assertIsInstance(body.get("tag_name"), str)
    for key, value in body.items():
        test.assertIn(key, RELEASE_WRITE_FIELDS, f"unknown release field {key}")
        rule = RELEASE_WRITE_FIELDS[key]
        if isinstance(rule, tuple):
            test.assertIsInstance(value, str, f"{key} must be a JSON string")
            test.assertIn(value, rule)
        else:
            test.assertIs(type(value), rule, f"{key} must be a JSON {rule.__name__}")



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
        "desktopSourceTag": tag,
        "desktopClaimTag": "",
        "desktopClaimObject": "",
        "upstreamChannel": "canary",
        "desktopVersion": desktop_version,
        "desktopFeedUrl": light.CANARY_FEED_URL,
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
        self.version = "v0.21.6+canary.20261009T070410Z-r1"
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
            "desktopSourceTag": tag,
            "desktopClaimTag": "",
            "desktopClaimObject": "",
            "desktopCommit": self.commit,
            "desktopFeedUrl": light.CANARY_FEED_URL,
            "desktopFeedEtag": record["desktopFeedEtag"],
            "desktopFeedLastModified": record["desktopFeedLastModified"],
            "desktopArtifactUrl": record["desktopArtifactUrl"],
            "desktopArtifactSha256": record["desktopArtifactSha256"],
            "desktopSourceUrl": light.CANARY_FEED_URL,
        }
        return record, live, artifact

    def _publish_environment(self, record, root):
        return {
            "PACKAGE_VERSION": record["version"],
            "SOURCE_REF": record["commit"],
            "UPSTREAM_TAG": record["desktopTag"],
            "UPSTREAM_SOURCE_TAG": record["desktopSourceTag"],
            "UPSTREAM_CLAIM_TAG": record["desktopClaimTag"],
            "UPSTREAM_CLAIM_OBJECT": record["desktopClaimObject"],
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
            artifact="hermes-desktop-light-v0.21.6+canary.20261009T070410Z-r1-windows-x64.zip",
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
                    light._publish_desktop(CANARY)
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

    def test_created_draft_is_reused_when_release_list_lags(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            record, live, artifact = self._fixture(root)
            release_tag = light.release_tag(light.APP, self.version)
            release_rows = Mock(side_effect=[[], []])
            api_write = Mock(return_value={"id": 42, "tag_name": release_tag, "draft": True, "prerelease": True})
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
                     patch.object(light, "api_write", api_write), \
                     patch.object(light, "gh", gh), \
                     patch.object(light, "_writeback", writeback), \
                     patch("urllib.request.urlopen", return_value=response):
                    light._publish_desktop(CANARY)
            finally:
                os.chdir(previous)
            release_rows.assert_called_once_with("example/bucket")
            api_write.assert_called_once()
            self.assertEqual(api_write.call_args.args[:2], ("repos/example/bucket/releases", "POST"))
            self.assertIn(("repos/example/bucket/releases/42",), [call.args for call in api.call_args_list])
            self.assertFalse(any(call.args[:2] == ("release", "create") for call in gh.call_args_list))
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

    def test_created_release_response_must_match_requested_identity(self):
        mismatches = {
            "tag": lambda created: created.update(tag_name="other/tag"),
            "draft": lambda created: created.update(draft=False),
            "prerelease": lambda created: created.update(prerelease=False),
        }
        for field, mutate in mismatches.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as scratch:
                root = Path(scratch)
                record, live, _artifact = self._fixture(root)
                created = {"id": 42, "tag_name": light.release_tag(light.APP, self.version), "draft": True, "prerelease": True}
                mutate(created)
                release_rows = Mock(return_value=[])
                api_write = Mock(return_value=created)
                api = Mock()
                gh = Mock()
                writeback = Mock()
                previous = Path.cwd()
                os.chdir(root)
                try:
                    with patch.dict(os.environ, self._publish_environment(record, root), clear=False), \
                         patch.object(light, "_desktop_feed", return_value={}), \
                         patch.object(light, "_desktop_provenance", return_value=live), \
                         patch.object(light, "_release_rows", release_rows), \
                         patch.object(light, "api", api), \
                         patch.object(light, "api_write", api_write), \
                         patch.object(light, "gh", gh), \
                         patch.object(light, "_writeback", writeback):
                        with self.assertRaises(ValueError):
                            light._publish_desktop(CANARY)
                finally:
                    os.chdir(previous)
                release_rows.assert_called_once_with("example/bucket")
                api_write.assert_called_once()
                api.assert_not_called()
                gh.assert_not_called()
                writeback.assert_not_called()


    def test_reused_draft_refreshes_notes_but_published_release_stays_unchanged(self):
        for draft in (True, False):
            with self.subTest(draft=draft), tempfile.TemporaryDirectory() as scratch:
                root = Path(scratch)
                record, live, artifact = self._fixture(root)
                release_tag = light.release_tag(light.APP, self.version)
                release_rows = Mock(
                    return_value=[{"tag_name": release_tag, "id": 42, "draft": draft, "prerelease": True, "assets": []}]
                )
                events = []

                def fake_api(*args):
                    events.append(("api", args))
                    if args[0].endswith("/releases/42"):
                        return {"assets": []}
                    return {"draft": False, "prerelease": True}

                def fake_api_write(endpoint, method, payload):
                    events.append(("write", (endpoint, method, payload)))
                    return {"id": 42, "tag_name": release_tag, "draft": True, "prerelease": True}

                def fake_gh(*args):
                    events.append(("gh", args))
                    return ""

                api = Mock(side_effect=fake_api)
                api_write = Mock(side_effect=fake_api_write)
                gh = Mock(side_effect=fake_gh)
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
                         patch.object(light, "api_write", api_write), \
                         patch.object(light, "gh", gh), \
                         patch.object(light, "_writeback", writeback), \
                         patch("urllib.request.urlopen", return_value=response):
                        light._publish_desktop(CANARY)
                finally:
                    os.chdir(previous)
                upload_index = next(
                    index for index, (kind, args) in enumerate(events) if kind == "gh" and args[:2] == ("release", "upload")
                )
                patch_events = [
                    (index, args) for index, (kind, args) in enumerate(events) if kind == "write"
                ]
                if draft:
                    endpoint, method, payload = patch_events[0][1]
                    self.assertEqual((endpoint, method), ("repos/example/bucket/releases/42", "PATCH"))
                    self.assertTrue(payload["name"].startswith("Unofficial Hermes Desktop Light"))
                    self.assertIn(record["sha256"], payload["body"])
                    self.assertIn(record["bucketCommit"], payload["body"])
                    self.assertLess(patch_events[0][0], upload_index)
                else:
                    self.assertFalse(patch_events)
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
                            light._publish_desktop(CANARY)
                finally:
                    os.chdir(previous)
                release_rows.assert_not_called()
                api.assert_not_called()
                gh.assert_not_called()
                writeback.assert_not_called()
                self.assertFalse((root / "output" / f"{light.APP}.json").exists())

    def test_manifest_points_to_immutable_unofficial_release_and_pointer(self):
        data = light.manifest(self.version, "takano536/scoop-bucket", self.digest, channel=CANARY)
        self.assertEqual(data["architecture"]["64bit"]["hash"], self.digest)
        self.assertIn("hermes-desktop-light%2Fv0.21.6%2Bcanary.20261009T070410Z-r1", data["architecture"]["64bit"]["url"])
        self.assertEqual(data["shortcuts"], [["hermes-light-canary.exe", "Hermes Desktop Light Canary (Unofficial)"]])
        self.assertIn("metadata/hermes-desktop-light-release.json", data["checkver"]["url"])
        self.assertIn("officially published Hermes Desktop canary", data["notes"])

    def test_release_pointer_records_both_upstream_and_bucket_identity(self):
        pointer = light.release_pointer(
            version=self.version,
            digest=self.digest,
            commit=self.commit,
            desktop_version="26.1009.7.410",
            desktop_tag="v0.21.6+canary.20261009T070410Z",
            desktop_feed_url=light.CANARY_FEED_URL,
            desktop_feed_etag='"feed"',
            desktop_feed_last_modified="Fri, 09 Oct 2026 08:04:40 GMT",
            desktop_artifact_url="https://example.invalid/HermesBundled.msixbundle",
            desktop_artifact_sha256=self.desktop_digest,
            conditions_fingerprint=self.conditions,
            license_sha256=self.license,
            release_tag_value=f"{light.APP}/{self.version}",
            artifact=f"{light.APP}-{self.version}-windows-x64.zip",
            channel=CANARY,
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
                version="v0.21.6+canary.20261009T070410Z",
                digest=self.digest,
                commit=self.commit,
                desktop_version="26.1009.7.410",
                desktop_tag="v0.21.6+canary.20261009T070410Z",
                desktop_feed_url=light.CANARY_FEED_URL,
                desktop_feed_etag="",
                desktop_feed_last_modified="",
                desktop_artifact_url="https://example.invalid/a",
                desktop_artifact_sha256=self.desktop_digest,
                conditions_fingerprint=self.conditions,
                license_sha256=self.license,
                release_tag_value="tag",
                artifact="artifact.zip",
            )


class GitHubReleaseWireContractTests(unittest.TestCase):
    """Exercise the real `gh` argv/stdin boundary instead of mocking `api`."""

    def _run_publish(self, rows):
        fixture = PublishContractTests()
        fixture.setUp()
        requests = []
        tag = light.release_tag(light.APP, fixture.version)

        def fake_check_output(argv, **kwargs):
            if argv[:2] != ["gh", "api"]:
                self.assertEqual(argv[0], "gh")
                return ""
            endpoint, method, body = _gh_api_request(argv, kwargs.get("input"))
            requests.append((endpoint, method, body))
            if endpoint.startswith("repos/example/bucket/releases/tags/"):
                return json.dumps({"draft": False, "prerelease": True})
            if endpoint == "repos/example/bucket/releases/42" and method == "GET":
                return json.dumps({"assets": []})
            return json.dumps({"id": 42, "tag_name": tag, "draft": True, "prerelease": True})

        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            record, live, artifact = fixture._fixture(root)
            response = _BytesResponse(artifact.read_bytes())
            previous = Path.cwd()
            os.chdir(root)
            try:
                with patch.dict(os.environ, fixture._publish_environment(record, root), clear=False), \
                     patch.object(light, "_desktop_feed", return_value={}), \
                     patch.object(light, "_desktop_provenance", return_value=live), \
                     patch.object(light, "_release_rows", Mock(return_value=rows(tag))), \
                     patch.object(light.subprocess, "check_output", side_effect=fake_check_output), \
                     patch.object(light, "_writeback", Mock()), \
                     patch("urllib.request.urlopen", return_value=response):
                    light._publish_desktop(CANARY)
            finally:
                os.chdir(previous)
        notes = light._release_notes(record, live, record["desktopTag"], record["commit"], record["desktopVersion"], CANARY)
        return tag, notes, requests

    def test_new_release_create_body_matches_github_schema(self):
        tag, notes, requests = self._run_publish(lambda _tag: [])
        creates = [body for endpoint, method, body in requests if method == "POST"]
        self.assertEqual(len(creates), 1)
        body = creates[0]
        _assert_release_write_body(self, body, create=True)
        self.assertEqual(body["tag_name"], tag)
        self.assertEqual(body["target_commitish"], "main")
        self.assertIs(body["draft"], True)
        self.assertIs(body["prerelease"], True)
        self.assertEqual(body["make_latest"], "false")
        self.assertEqual(body["body"], notes)

    def test_reused_draft_update_body_matches_github_schema(self):
        _tag, notes, requests = self._run_publish(
            lambda tag: [{"tag_name": tag, "id": 42, "draft": True, "prerelease": True, "assets": []}]
        )
        updates = [body for endpoint, method, body in requests if method == "PATCH"]
        self.assertEqual(len(updates), 1)
        _assert_release_write_body(self, updates[0], create=False)
        self.assertEqual(updates[0]["body"], notes)
        self.assertFalse([body for endpoint, method, body in requests if method == "POST"])

    def test_api_failure_reports_github_error_without_request_body(self):
        api_error = "gh: Invalid request.\n\nFor 'properties/make_latest', false is not a string. (HTTP 422)\n"
        failure = light.subprocess.CalledProcessError(
            1,
            ["gh", "api", "repos/example/bucket/releases", "--method", "POST", "--input", "-"],
            stderr=api_error,
        )
        stderr = io.StringIO()
        with patch.object(light, "publish", side_effect=failure), redirect_stderr(stderr):
            self.assertEqual(light.main(["publish"]), 2)
        report = stderr.getvalue()
        self.assertTrue(report.startswith("::error::"))
        self.assertEqual(report.count("\n"), 1, "workflow command must stay on one line")
        self.assertIn("gh api repos/example/bucket/releases --method POST", report)
        self.assertIn("(HTTP 422)", report)
        self.assertIn("For 'properties/make_latest', false is not a string.", report)


if __name__ == "__main__":
    unittest.main()
