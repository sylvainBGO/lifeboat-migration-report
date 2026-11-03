import ast
import csv
from pathlib import Path
import tempfile
from typing import Any
import unittest
from unittest.mock import patch
from manifest_benchmark import run_suite
from manifest_index import ManifestIndex
from manifest_benchmark import baseline, run


def upstream_selector():
    source = Path(__file__).resolve().parents[1] / 'src/codex_transfer/restore.py'
    if not source.exists():
        return baseline
    tree = ast.parse(source.read_text(encoding='utf-8'))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_project_manifest_entries')
    ns = {'Path': Path, 'Any': Any, 'csv': csv}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), 'exec'), ns)
    return ns[fn.name]


class IndexTests(unittest.TestCase):
    def test_selection_matches_upstream_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'manifest').mkdir()
            rows = [('projects/a/x', '1', 'ABC'), ('projects/a/nested/y', '2', 'DEF'),
                    ('projects/ab/x', '3', 'AAA'), ('projects/é/日本\n.csv', '4', 'BBB'),
                    ('projects/a/x', '5', 'CCC'), ('unrelated/z', 'invalid', 'DDD')]
            with (root / 'manifest/sha256.csv').open('w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['relative_path', 'size', 'sha256'])
                writer.writerows(rows)
            selector = upstream_selector()
            with ManifestIndex(root, directory=root) as index:
                for prefix in ('projects/a', 'projects/a/', 'projects/a/nested', 'projects/ab', 'projects/é', 'missing'):
                    project = {'backupRelativePath': prefix}
                    self.assertEqual(selector(root, project), index.select(project))
                    self.assertEqual(selector(root, project), baseline(root, project))
                self.assertEqual(index.rows_read, len(rows))
                with self.assertRaises(ValueError):
                    index.select({'backupRelativePath': 'unrelated'})
                self.assertGreater(index.disk_bytes, 0)
            self.assertEqual([p.name for p in root.iterdir()], ['manifest'])

    def test_packaged_scenario(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(Path(tmp), rows=51, projects=4, repeats=2)
            self.assertTrue(result['completed'])
            self.assertEqual(len(result['results']), 4)
            self.assertTrue(all(r['identical_results'] for r in result['results']))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_suite_retains_completed_scenario_on_failure(self):
        snapshots = []
        import copy
        with tempfile.TemporaryDirectory() as tmp:
            with patch('manifest_benchmark.run', side_effect=[{'completed': True}, OSError('full')]):
                with self.assertRaises(OSError):
                    run_suite(Path(tmp), lambda r: snapshots.append(copy.deepcopy(r)))
        self.assertEqual(len(snapshots[-1]['scenarios']), 1)
        self.assertFalse(snapshots[-1]['completed'])
        self.assertEqual(snapshots[-1]['error_type'], 'OSError')

    def test_suite_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_suite(Path(tmp), lambda r: None, ((12, 3, 1), (24, 3, 1)))
        self.assertTrue(report['completed'])
        self.assertEqual(len(report['scenarios']), 2)

    def test_creation_failure_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                ManifestIndex(tmp, directory=tmp)
            self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
