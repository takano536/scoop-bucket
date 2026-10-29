"""Application-scoped Desktop release identity and numeric revision ordering."""
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import distribution


class DistributionTests(unittest.TestCase):
    def test_scoped_tags_and_revision_order(self):
        version = "v0.21.6+canary.20261009T070410Z-r1"
        self.assertEqual(distribution.release_tag("hermes-desktop-light", version), f"hermes-desktop-light/{version}")
        self.assertNotEqual(distribution.release_tag("other-app", version), distribution.release_tag("hermes-desktop-light", version))
        self.assertLess(distribution.version_key("v0.21.6+canary.20261009T070410Z-r1"), distribution.version_key("v0.21.6+canary.20261009T070410Z-r2"))
        self.assertLess(distribution.version_key("v0.21.6+canary.20261009T070410Z-r2"), distribution.version_key("v0.21.6+canary.20261010T070410Z-r1"))
        self.assertLess(distribution.version_key("v0.21.5+canary.20261009T070410Z-r1"), distribution.version_key("v0.21.6+canary.20261009T070410Z-r1"))
        self.assertEqual(distribution.package_version("v0.21.6+canary.20261009T070410Z", "2"), "v0.21.6+canary.20261009T070410Z-r2")

    def test_old_published_version_upgrades_to_desktop_release_format(self):
        old = "0.0.0-alpha.dev.1-r1"
        new = "v0.22.5+canary.20261023T070057Z-r1"
        self.assertLess(distribution.distribution_version_key(old), distribution.distribution_version_key(new))
        self.assertLess(distribution.distribution_version_key("26.1023.7.57-alpha.dev.1-r1"), distribution.distribution_version_key(new))
        self.assertLess(distribution.distribution_version_key("2026.6864.2132.0-r1"), distribution.distribution_version_key("rc.3-v0.22.0-r1"))

    def test_stable_product_order_is_after_unofficial_alpha_build(self):
        # Already published versions keep their historical ordering so the
        # official-tag migration never reorders an installed machine.
        light = "26.1009.7.410-alpha.dev.1-r2"
        stable = "26.1009.7.410-r1"
        future = "26.1010.1.100-r1"
        self.assertLess(distribution.distribution_version_key(light), distribution.distribution_version_key(stable))
        self.assertLess(distribution.distribution_version_key(stable), distribution.distribution_version_key(future))

    def test_stable_channel_uses_the_official_build_tag(self):
        version = distribution.package_version("rc.3-v0.22.0", 1)
        self.assertEqual(version, "rc.3-v0.22.0-r1")
        self.assertNotIn("alpha.dev", version)
        self.assertEqual(
            distribution.release_tag("hermes-desktop-light", version),
            f"hermes-desktop-light/{version}",
        )
        self.assertEqual(
            distribution.artifact_name("hermes-desktop-light", version),
            f"hermes-desktop-light-{version}-windows-x64.zip",
        )
        self.assertEqual(distribution.package_version("v0.22.5+canary.20261023T070057Z", 2), "v0.22.5+canary.20261023T070057Z-r2")
        # Same stable channel: rc number first, then the bucket revision.
        self.assertLess(
            distribution.distribution_version_key("rc.3-v0.22.0-r1"),
            distribution.distribution_version_key("rc.3-v0.22.0-r2"),
        )
        self.assertLess(
            distribution.distribution_version_key("rc.3-v0.22.0-r9"),
            distribution.distribution_version_key("rc.3-v0.22.0-r10"),
        )
        self.assertLess(
            distribution.distribution_version_key("rc.3-v0.22.0-r2"),
            distribution.distribution_version_key("rc.4-v0.22.1-r1"),
        )
        # Same canary channel: build stamp first, then the bucket revision.
        self.assertLess(
            distribution.distribution_version_key("v0.22.5+canary.20261023T070057Z-r1"),
            distribution.distribution_version_key("v0.22.5+canary.20261024T065630Z-r1"),
        )
        self.assertLess(
            distribution.distribution_version_key("v0.22.5+canary.20261023T070057Z-r9"),
            distribution.distribution_version_key("v0.22.5+canary.20261023T070057Z-r10"),
        )
        self.assertLess(
            distribution.distribution_version_key("v0.22.4+canary.20261022T070155Z-r1"),
            distribution.distribution_version_key("v0.22.5+canary.20261023T070057Z-r1"),
        )
        self.assertLess(
            distribution.distribution_version_key("2026.6864.2132.0-r1"),
            distribution.distribution_version_key("rc.3-v0.22.0-r1"),
        )

    def test_unknown_channel_or_stable_identity_fails_closed(self):
        # A Light version is exactly one official Desktop build tag plus this
        # bucket's revision; a bare product version or unknown tag never
        # becomes a publishable identity.
        for tag in ("2026.6864.2132.0", "rc.0-v0.22.0", "v0.22.5", "canary.20261023T070057Z"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                distribution.package_version(tag, 1)
        for version in ("rc.3-v0.22.0", "v0.22.5+canary.20261023T070057Z", "0.0.0-alpha.dev.1-r0", "v0.22.5+canary.20261023T070057Z-r1-extra"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                distribution.light_package_version(version)

    def test_invalid_identities_fail_closed(self):
        for version in (
            "v0.22.5",
            "rc.3-v0.22.0",
            "v0.22.5+canary.20261023T070057Z",
            "v0.22.5+canary.20261023T070057Z-r0",
            "rc.0-v0.22.0-r1",
            "v0.22.5+canary.20261023T070057Z-r01",
            "rc.3-v0.22.0-r01",
            "../v0.22.5+canary.20261023T070057Z-r1",
        ):
            with self.subTest(version=version), self.assertRaises(ValueError):
                distribution.light_version_key(version)
        for app in ("../escape", "app/name", "UPPER"):
            with self.assertRaises(ValueError):
                distribution.release_tag(app, "v0.22.5+canary.20261023T070057Z-r1")
        for revision in ("0", "01", "-1", "x"):
            with self.assertRaises(ValueError):
                distribution.package_version("v0.22.5+canary.20261023T070057Z", revision)


if __name__ == "__main__":
    unittest.main()
