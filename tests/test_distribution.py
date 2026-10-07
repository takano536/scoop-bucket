"""Application-scoped distribution identity and numeric revision ordering."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import distribution


class DistributionTests(unittest.TestCase):
    def test_scoped_tags_and_revision_order(self):
        self.assertEqual(distribution.release_tag('hermes-agent-light', '0.22.0-r1'), 'hermes-agent-light/v0.22.0-r1')
        self.assertNotEqual(distribution.release_tag('other-app', '0.22.0-r1'), distribution.release_tag('hermes-agent-light', '0.22.0-r1'))
        self.assertLess(distribution.version_key('0.22.0-r2'), distribution.version_key('0.22.0-r10'))
        self.assertLess(distribution.version_key('0.22.0-r10'), distribution.version_key('0.23.0-r1'))
        self.assertEqual(distribution.package_version('0.22.0', '2'), '0.22.0-r2')

    def test_invalid_identities_fail_closed(self):
        for version in ('0.22.0', '0.22.0-r0', '0.22.0-r01', '0.22.0-rc.1', '../0.22.0-r1'):
            with self.assertRaises(ValueError):
                distribution.version_key(version)
        for app in ('../escape', 'app/name', 'UPPER'):
            with self.assertRaises(ValueError):
                distribution.release_tag(app, '0.22.0-r1')
        for revision in ('0', '01', '-1', 'x'):
            with self.assertRaises(ValueError):
                distribution.package_version('0.22.0', revision)


if __name__ == '__main__':
    unittest.main()
