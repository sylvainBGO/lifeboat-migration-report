import os
import shutil
import tempfile
import unittest
from codex_transfer.fs_paths import Path, extended_windows_path, ordinary_windows_path

class PathSyntaxTests(unittest.TestCase):
    def test_drive_and_dot_segments(self):
        self.assertEqual(extended_windows_path(r'C:\a\..\b'), '\\\\?\\C:\\b')
    def test_unc(self):
        self.assertEqual(extended_windows_path(r'\\server\share\folder'), '\\\\?\\UNC\\server\\share\\folder')
    def test_round_trip(self):
        for value in [r'C:\a\b', r'\\server\share\folder']:
            self.assertEqual(ordinary_windows_path(extended_windows_path(value)), value)
    def test_existing_prefix(self):
        value = '\\\\?\\C:\\a'
        self.assertEqual(extended_windows_path(value), value)

@unittest.skipUnless(os.name == 'nt', 'Win32 filesystem test')
class WindowsFilesystemTests(unittest.TestCase):
    @__import__("contextlib").contextmanager
    def cleanup_deep(self, directory):
        try:
            yield
        finally:
            shutil.rmtree(Path(directory))

    def test_deep_read_copy_walk_and_missing_file(self):
        with tempfile.TemporaryDirectory() as temporary, self.cleanup_deep(temporary):
            root=Path(temporary).resolve()
            deep=root / ('directory-' * 12) / ('directory-' * 12)
            deep.mkdir(parents=True)
            source=deep / 'database.sqlite'
            source.write_bytes(b'not a real database')
            self.assertGreater(len(str(source)), 260)
            self.assertTrue(source.is_file())
            from codex_transfer.windows import long_paths_enabled
            from pathlib import Path as OrdinaryPath
            if long_paths_enabled() is False:
                with self.assertRaises(OSError):
                    OrdinaryPath(str(source)).stat()
            self.assertFalse(str(source).startswith('\\\\?\\'))
            self.assertTrue(os.fspath(source).startswith('\\\\?\\'))
            self.assertEqual(Path(os.fspath(source)), source)
            self.assertEqual(source.resolve(), source)
            self.assertIn(source, list(root.rglob('*')))
            files=[Path(folder)/name for folder, _, names in os.walk(root) for name in names]
            self.assertIn(source, files)
            target=root/'copy'
            shutil.copytree(deep, target)
            self.assertEqual((target/source.name).read_bytes(), source.read_bytes())
            source.unlink()
            self.assertFalse(source.exists())
