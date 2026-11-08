"""Production-path contracts on tiny synthetic fixtures, not performance data."""
import json
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest

from benchmark_report import PROTOCOL_VERSION
from restore_worker import complete_target_fixture, review_synthetic_plan


BENCHMARKS = Path(__file__).resolve().parent
REPOSITORY = BENCHMARKS.parent.parent


class ProductionPathTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32', 'Real production workers require winreg and Windows path APIs')
    def test_real_paths_keep_all_production_guards_and_a_valid_comparison_plan(self):
        candidates = {
            'baseline': [REPOSITORY / 'baseline' / 'src', REPOSITORY.parent / 'lifeboat-baseline' / 'src'],
            'final': [REPOSITORY / 'upstream' / 'src', REPOSITORY.parent / 'lifeboat-community' / 'src'],
        }
        sources = {variant: next((path for path in paths if (path / 'codex_transfer' / 'restore.py').is_file()), None)
                   for variant, paths in candidates.items()}
        if not all(sources.values()):
            self.skipTest('Pinned baseline and integrated final sources are required for this production contract')
        # Separate imports are essential: neither build can borrow modules from
        # the other. The spy calls the real guard; it never bypasses tasklist.
        program = '''import json,pathlib,sys
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
import restore_worker as worker
from codex_transfer import backup
root=pathlib.Path(sys.argv[3])
variant=sys.argv[4]
worker.save(root/'.lifeboat-benchmark-owned.json', {'purpose':'synthetic-lifeboat-benchmark','token':'contract'})
worker.isolate(root, 'contract')
worker.profile_shape=lambda profile,mode: (3,32,1)
worker.build_fixture(root, 'small', 'quick')
guards=[]
real_guard=backup.check_codex_not_running
def observed_guard(path, allow_running_test):
    guards.append(allow_running_test)
    return real_guard(path, allow_running_test)
backup.check_codex_not_running=observed_guard
result=worker.restore_trial(root, 'contract', variant)
mapping_file=next((root/'packages'/'contract').glob('*/manifest/path-mappings.json'))
mappings=json.loads(mapping_file.read_text(encoding='utf-8'))
locations=[item['location']['kind'] for item in mappings['projects'] if item.get('sourcePresent', True)]
worker.save(root/'contract.json', {'result':result,'guards':guards,'project_locations':locations})
'''
        for variant, count in (('baseline', 3), ('final', 4), ('final_archive', 4)):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory(prefix='lb-contract-') as folder:
                source = sources['baseline' if variant == 'baseline' else 'final']
                completed = subprocess.run([sys.executable, '-c', program, str(BENCHMARKS), str(source), folder, variant],
                                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=90)
                self.assertEqual(completed.returncode, 0, completed.stdout[-3000:] + completed.stderr[-3000:])
                evidence = json.loads((Path(folder) / 'contract.json').read_text(encoding='utf-8'))
                self.assertEqual(evidence['guards'], [False] * count)
                self.assertEqual(evidence['project_locations'], ['known-folder'])
                row = evidence['result']
                self.assertTrue(row['valid'], row['checks'])
                self.assertTrue(row['checks']['target_conversation_preserved'])
                self.assertEqual(row['verification']['threads'], 4)
                self.assertEqual(row['verification']['recentIndexEntries'], 3)
                self.assertEqual(row['protocol_version'], PROTOCOL_VERSION)
                self.assertIn({'kind': 'project', 'decision': 'keep-source'}, row['synthetic_plan_decisions'])
                self.assertIn({'kind': 'conversation', 'decision': 'keep-target'}, row['synthetic_plan_decisions'])
                self.assertAlmostEqual(row['seconds'], row['plan_seconds'] + row['prepare_seconds'] + row['restore_seconds'])
                self.assertAlmostEqual(row['total_seconds'], row['backup_seconds'] + row['seconds'])
                for key in ('plan_seconds', 'prepare_seconds', 'restore_seconds', 'backup_seconds'):
                    self.assertGreater(row[key], 0)

    def test_target_rollout_and_index_match_the_existing_database_without_changing_it(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder).resolve()
            codex = profile / '.codex'
            codex.mkdir()
            project = profile / 'Documents' / 'DemoProject'
            project.mkdir(parents=True)
            database = codex / 'state_5.sqlite'
            connection = sqlite3.connect(database)
            try:
                connection.execute('CREATE TABLE threads(id TEXT,rollout_path TEXT,cwd TEXT,cli_version TEXT,'
                                   'first_user_message TEXT,title TEXT,created_at INTEGER,updated_at INTEGER,archived INTEGER)')
                connection.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,?)',
                    ('old-SYNTHETIC', str(codex / 'sessions' / 'old.jsonl'), str(project),
                     'target', 'old', 'Old', 1, 1, 0))
                connection.commit()
            finally:
                connection.close()
            original_database = database.read_bytes()
            rollout, _ = complete_target_fixture(codex)
            records = [json.loads(line) for line in rollout.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(records[0]['type'], 'session_meta')
            self.assertEqual(records[0]['payload']['id'], 'old-SYNTHETIC')
            self.assertEqual(records[0]['payload']['cwd'], str(project))
            self.assertEqual(records[0]['payload']['cli_version'], 'target')
            self.assertEqual(records[1]['payload'], {'type': 'user_message', 'message': 'old'})
            self.assertEqual(json.loads((codex / 'session_index.jsonl').read_text(encoding='utf-8')),
                             {'id': 'old-SYNTHETIC', 'title': 'Old'})
            self.assertEqual(database.read_bytes(), original_database)
            with self.assertRaisesRegex(RuntimeError, 'already exist'):
                complete_target_fixture(codex)

    def test_deterministic_decisions_cannot_apply_outside_marked_fixture_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            package, target = root / 'packages' / 'trial', root / 'targets' / 'trial'
            plan = {'package': str(package), 'targetProfile': str(target), 'ready': True, 'items': []}
            api = SimpleNamespace()
            with self.assertRaisesRegex(RuntimeError, 'owned synthetic fixture'):
                review_synthetic_plan(root, package, target, plan, api)
            (root / '.lifeboat-benchmark-owned.json').write_text(
                json.dumps({'purpose': 'synthetic-lifeboat-benchmark', 'token': 'contract'}), encoding='utf-8')
            (root / 'fixture.json').write_text(json.dumps({'synthetic': True}), encoding='utf-8')
            plan['items'] = [{'kind': 'project', 'key': 'project/outside', 'source': str(root.parent / 'user-project'),
                              'target': str(target / 'project'), 'blocking': True, 'availableDecisions': ['keep-source']}]
            with self.assertRaisesRegex(RuntimeError, 'source is outside'):
                review_synthetic_plan(root, package, target, plan, api)
            plan['items'][0]['source'] = str(root / 'source' / 'project')
            plan['items'][0]['target'] = str(root.parent / 'user-destination')
            with self.assertRaisesRegex(RuntimeError, 'destination is outside'):
                review_synthetic_plan(root, package, target, plan, api)


if __name__ == '__main__':
    unittest.main()
