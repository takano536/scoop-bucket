import importlib.util
from pathlib import Path
import tempfile
import unittest
import json
import subprocess
import sys


class ReadmeTests(unittest.TestCase):
    def test_cli_check_detects_stale_table_and_generation_is_idempotent(self):
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'update-readme.py'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'bucket').mkdir()
            readme = root / 'README.md'
            readme.write_text('Intro\n<!-- BEGIN GENERATED APPS -->\nstale\n<!-- END GENERATED APPS -->\n', encoding='utf-8')
            command = [sys.executable, str(script), '--root', str(root)]
            self.assertEqual(subprocess.run(command + ['--check'], capture_output=True).returncode, 1)
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(subprocess.run(command + ['--check'], capture_output=True).returncode, 0)
            first = readme.read_bytes()
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(readme.read_bytes(), first)
            readme.write_text('No markers\n', encoding='utf-8')
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(readme.read_text(), 'No markers\n')

    def test_invalid_manifest_fails_without_writing_readme(self):
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'update-readme.py'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'bucket').mkdir()
            before = '<!-- BEGIN GENERATED APPS -->\n<!-- END GENERATED APPS -->\n'
            (root / 'README.md').write_text(before, encoding='utf-8')
            for manifest in ({'version': 2}, {'version': '2', 'homepage': 'javascript:alert(1)'}, None):
                (root / 'bucket' / 'bad.json').write_text(json.dumps(manifest) if manifest is not None else '{', encoding='utf-8')
                result = subprocess.run([sys.executable, str(script), '--root', str(root)], capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((root / 'README.md').read_text(), before)

    def test_generate_sorted_manifest_table_preserving_surrounding_text(self):
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'update-readme.py'
        self.assertTrue(script.is_file(), 'README generator must exist')
        spec = importlib.util.spec_from_file_location('readme_generator', script)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'bucket').mkdir()
            for name in ('zebra', 'Alpha'):
                (root / 'bucket' / f'{name}.json').write_text(json.dumps({
                    'version': '2026-10', 'description': 'A | B\nsecond line',
                    'homepage': 'https://example.com/' + name,
                }), encoding='utf-8')
            (root / 'bucket' / 'ignored.json.template').write_text('not JSON')
            before = 'Intro\n<!-- BEGIN GENERATED APPS -->\nold\n<!-- END GENERATED APPS -->\nFooter\n'
            result = module.generate(root, before)
            self.assertTrue(result.startswith('Intro\n'))
            self.assertTrue(result.endswith('\nFooter\n'))
            self.assertLess(result.index('[Alpha]'), result.index('[zebra]'))
            self.assertIn('A &#124; B second line', result)
            self.assertIn('| リンク |', result)
            self.assertIn('[example.com/Alpha](https://example.com/Alpha)', result)
            self.assertNotIn('ignored', result)
            self.assertEqual(module.generate(root, result), result)
            cases = (
                ('https://example.com/', '[example.com](https://example.com/)'),
                ('http://example.com/docs/', '[example.com/docs](http://example.com/docs/)'),
                ('https://example.com/a[b]|c', '[example.com/a&#91;b&#93;&#124;c](https://example.com/a%5Bb%5D%7Cc)'),
                ('', '| — |'),
            )
            for homepage, expected in cases:
                with self.subTest(homepage=homepage):
                    (root / 'bucket' / 'Alpha.json').write_text(json.dumps({
                        'version': '1', 'homepage': homepage,
                    }), encoding='utf-8')
                    self.assertIn(expected, module.generate(root, before))


if __name__ == '__main__':
    unittest.main()
