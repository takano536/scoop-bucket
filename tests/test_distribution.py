"""Application-scoped Desktop release identity and numeric revision ordering."""
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import distribution


class DistributionTests(unittest.TestCase):
    def test_scoped_tags_and_revision_order(self):
        version = "26.1009.7.410-alpha.dev.1-r1"
        self.assertEqual(distribution.release_tag("hermes-desktop-light", version), f"hermes-desktop-light/v{version}")
        self.assertNotEqual(distribution.release_tag("other-app", version), distribution.release_tag("hermes-desktop-light", version))
        self.assertLess(distribution.version_key("26.1009.7.410-alpha.dev.1-r1"), distribution.version_key("26.1009.7.410-alpha.dev.1-r2"))
        self.assertLess(distribution.version_key("26.1009.7.410-alpha.dev.1-r2"), distribution.version_key("26.1010.1.100-alpha.dev.1-r1"))
        self.assertEqual(distribution.package_version("26.1009.7.410", "2"), "26.1009.7.410-alpha.dev.1-r2")

    def test_old_published_version_upgrades_to_desktop_release_format(self):
        old = "0.0.0-alpha.dev.1-r1"
        new = "26.1009.7.410-alpha.dev.1-r1"
        self.assertLess(distribution.distribution_version_key(old), distribution.distribution_version_key(new))

    def test_stable_product_order_is_after_unofficial_alpha_build(self):
        light = "26.1009.7.410-alpha.dev.1-r2"
        stable = "26.1009.7.410-r1"
        future = "26.1010.1.100-r1"
        self.assertLess(distribution.distribution_version_key(light), distribution.distribution_version_key(stable))
        self.assertLess(distribution.distribution_version_key(stable), distribution.distribution_version_key(future))

    def test_invalid_identities_fail_closed(self):
        for version in (
            "26.1009.7",
            "26.1009.7.410-alpha.dev.0-r1",
            "26.1009.7.410-alpha.dev.1-r0",
            "26.1009.7.410-alpha.dev.01-r1",
            "26.1009.7.410-r0",
            "../26.1009.7.410-alpha.dev.1-r1",
        ):
            with self.assertRaises(ValueError):
                distribution.light_version_key(version)
        for app in ("../escape", "app/name", "UPPER"):
            with self.assertRaises(ValueError):
                distribution.release_tag(app, "26.1009.7.410-alpha.dev.1-r1")
        for revision in ("0", "01", "-1", "x"):
            with self.assertRaises(ValueError):
                distribution.package_version("26.1009.7.410", revision)


if __name__ == "__main__":
    unittest.main()
