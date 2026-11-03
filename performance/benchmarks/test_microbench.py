import tempfile
import unittest
from pathlib import Path
from microbench import run, verify, digest, fused_copy, payload

class BenchmarkTests(unittest.TestCase):
    def test_strategies_and_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            sentinel = Path(folder)/'keep.txt'
            sentinel.write_text('user file')
            result = run(folder, count=12, size=200, repeats=1)
            self.assertEqual(len(result['results']), 6)
            self.assertTrue(all(x['verified'] for x in result['results']))
            self.assertEqual(list(Path(folder).iterdir()), [sentinel])
    def test_fixture_profiles(self):
        import zlib
        for profile in ('compressible', 'incompressible', 'mixed'):
            self.assertEqual(payload(2, 4096, profile), payload(2, 4096, profile))
        self.assertLess(len(zlib.compress(payload(1,4096,'compressible'))), 200)
        self.assertGreater(len(zlib.compress(payload(1,4096,'incompressible'))), 4000)

    def test_corruption_and_missing_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            file = root/'a'
            file.write_bytes(b'original')
            manifest = {'a': digest(file)}
            file.write_bytes(b'corrupt!')
            with self.assertRaises(ValueError): verify(root, manifest)
            with self.assertRaises(ValueError): fused_copy(root, root/'copy', manifest)
            file.unlink()
            with self.assertRaises(ValueError): verify(root, manifest)

if __name__ == '__main__': unittest.main()
