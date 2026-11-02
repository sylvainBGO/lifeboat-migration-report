import contextlib
import errno
import json
import os
import sqlite3
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
if os.name != 'nt':
    sys.modules.setdefault('winreg', types.ModuleType('winreg'))
from codex_transfer import rescue, restore, rollout, backup
from codex_transfer.fs_paths import Path


class RescueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.addCleanup(lambda: shutil.rmtree(self.base) if self.base.exists() else None)
        self.package = self.base / 'backup'
        self.profile = self.base / 'target'
        self.codex = self.profile / '.codex'
        self.safety = self.profile / 'AppData/Local/Codex Lifeboat/recovery-points/20261031-162112'
        self.safety.mkdir(parents=True)
        self.codex.mkdir(parents=True)
        (self.codex / 'auth.json').write_text('auth-untouched')
        self.journal = self.safety / 'restore-journal.json'
        self.plan = self.safety / 'reprise-plan.json'
        self.log = self.base / 'gui.txt'
        self.log.write_text('Replacing local portable Codex user data\n_restore_sessions\n_rewrite_copy\nNo space left on device')
        self.rows = []
        for name, folder, compressed in [('a', 'sessions', False), ('b', 'sessions', False),
                                          ('c', 'sessions', True), ('d', 'archived_sessions', False)]:
            source = self.package / 'codex' / folder / '2026/09/30' / (name + '.jsonl' + ('.zst' if compressed else ''))
            target = self.codex / source.relative_to(self.package / 'codex')
            content = json.dumps({'type': 'session_meta', 'payload': {'id': name}}) + '\n' + json.dumps({'text': 'C:/old/path'}) + '\n'
            with rollout.open_text_writer(source) as handle: handle.write(content)
            self.rows.append((name, source, target, folder == 'archived_sessions'))
        self.rows[0][2].parent.mkdir(parents=True)
        self.rows[0][2].write_bytes(self.rows[0][1].read_bytes())
        rescue.temporary_for(self.rows[1][2]).write_text('partial')
        # Portable profile may contain archived sessions not yet rewritten.
        self.rows[3][2].parent.mkdir(parents=True)
        self.rows[3][2].write_text('stale archive')
        self.db = self.safety / 'state_5.restored.tmp.sqlite'
        with contextlib.closing(sqlite3.connect(self.db)) as db:
            db.execute('CREATE TABLE threads(id TEXT, rollout_path TEXT, title TEXT, archived INTEGER)')
            db.executemany('INSERT INTO threads VALUES(?,?,?,?)', [(n, str(t), n, int(a)) for n,s,t,a in self.rows])
            db.commit()
        def write(relative, value):
            path = self.package / relative; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))
        write('manifest/package.json', {'source': {'profilePath': 'C:/old'}})
        write('manifest/projects.json', [])
        write('manifest/threads.json', [{'id': n, 'archived': a} for n,s,t,a in self.rows])
        write('manifest/path-mappings.json', {'projects': [], 'attachments': []})
        write('codex/portable-global-state.json', {'test-rescue': 'ok'})
        self.j = {'status': 'restoring', 'targetThreadsBefore': 0, 'targetProjectsBefore': 0,
                  'approvedExternalRoots': [], 'package': str(self.package), 'targetProfile': str(self.profile),
                  'safetyRoot': str(self.safety), 'projects': [{'status': 'complete', 'id': 'p', 'existedBefore': False}],
                  'comparisonPlan': {'items': []}}
        self.journal.write_text(json.dumps(self.j))
        for name, value in [('documents_folder', self.profile / 'Documents'), ('desktop_folder', self.profile / 'Desktop'),
                            ('project_registry_path', self.profile / 'registry.json'), ('lineage_state_path', self.profile / 'lineage.json'),
                            ('recovery_points_folder', self.safety.parent)]:
            p = patch('codex_transfer.windows.' + name, return_value=value); p.start(); self.addCleanup(p.stop)
        p = patch('codex_transfer.windows.known_folders', return_value={}); p.start(); self.addCleanup(p.stop)
        p = patch('codex_transfer.restore.resolved_external_roots', return_value={}); p.start(); self.addCleanup(p.stop)

    def prepare(self):
        return rescue.prepare(self.journal, self.log, self.plan)

    def test_prepare_under_threshold_never_walks_projects(self):
        with patch('codex_transfer.rescue.SpaceGuard.check', side_effect=AssertionError('guard in preparation')):
            p = self.prepare()
        self.assertEqual(len(p['reusedSessions']), 1)
        self.assertEqual(len(p['tasks']), 3)
        self.assertTrue(any('archived_sessions' in t['target'] for t in p['tasks']))
        self.assertEqual(backup.read_json(self.journal)['status'], 'restoring')

    def test_complete_real_roundtrip_and_second_launch_noop(self):
        self.prepare()
        original = self.rows[0][2].stat().st_mtime_ns
        # No sha256.csv exists: any accidental full final verification fails.
        with patch('codex_transfer.restore._restore_projects', side_effect=AssertionError('project recopy')), \
             patch('codex_transfer.restore._restore_portable_profile', side_effect=AssertionError('profile recopy')), \
             patch('codex_transfer.restore.rollback_restore', side_effect=AssertionError('rollback')):
            p = rescue.execute(self.plan)
        self.assertEqual(p['status'], 'complete')
        self.assertEqual(original, self.rows[0][2].stat().st_mtime_ns)
        self.assertTrue(self.db.exists())
        self.assertFalse(rescue.temporary_for(self.rows[1][2]).exists())
        for name,source,target,archived in self.rows:
            with rollout.open_text(target) as handle:
                self.assertEqual(json.loads(handle.readline())['payload']['id'], name)
        self.assertEqual(backup.read_json(self.journal)['status'], 'complete')
        self.assertTrue(Path(p['reportPath']).is_file())
        with patch('codex_transfer.rescue.SpaceGuard.check', side_effect=AssertionError('already complete')):
            self.assertEqual(rescue.execute(self.plan)['status'], 'complete')

    def test_low_space_blocks_execution_not_preparation(self):
        self.prepare()
        with patch('codex_transfer.rescue.shutil.disk_usage', return_value=types.SimpleNamespace(free=500_000_000)):
            with self.assertRaises(rescue.SpacePause): rescue.execute(self.plan)
        p = backup.read_json(self.plan)
        self.assertEqual(p['status'], 'paused-space')
        self.assertTrue(all(t['status'] == 'pending' for t in p['tasks']))
        self.assertEqual(rescue.execute(self.plan)['status'], 'complete')

    def test_mid_file_pause_retains_completed_and_restarts_only_partial(self):
        self.prepare()
        first = self.rows[1][2]
        real = rescue.SpaceGuard.check
        def check(guard, path, pending=0):
            if first.exists() and str(path).endswith('c.jsonl.zst') and pending:
                raise rescue.SpacePause('simulated mid-file pause')
            return real(guard, path, pending)
        with patch.object(rescue.SpaceGuard, 'check', check):
            with self.assertRaises(rescue.SpacePause): rescue.execute(self.plan)
        self.assertTrue(first.exists())
        stamp = first.stat().st_mtime_ns
        rescue.execute(self.plan)
        self.assertEqual(stamp, first.stat().st_mtime_ns)

    def test_enospc_during_checkpoint_does_not_mask_original(self):
        self.prepare()
        real_save = rescue._save
        def save(path, plan):
            if plan.get('lastError'): raise OSError(errno.ENOSPC, 'journal full')
            return real_save(path, plan)
        with patch('codex_transfer.rescue._save', side_effect=save), \
             patch('codex_transfer.rescue._write_task', side_effect=OSError(errno.ENOSPC, 'original copy failure')):
            with self.assertRaisesRegex(OSError, 'original copy failure'): rescue.execute(self.plan)
        self.assertEqual(backup.read_json(self.journal)['status'], 'restoring')
        self.assertEqual(rescue.execute(self.plan)['status'], 'complete')

    def test_crash_after_commit_before_checkpoint_is_idempotent(self):
        self.prepare()
        real_save = rescue._save
        crashed = False
        def save(path, plan):
            nonlocal crashed
            if not crashed and plan['tasks'][0]['status'] == 'done':
                crashed = True
                raise KeyboardInterrupt()
            return real_save(path, plan)
        with patch('codex_transfer.rescue._save', side_effect=save):
            with self.assertRaises(KeyboardInterrupt): rescue.execute(self.plan)
        self.assertEqual(backup.read_json(self.plan)['tasks'][0]['status'], 'pending')
        self.assertEqual(rescue.execute(self.plan)['status'], 'complete')

    def test_base_install_retry_does_not_lose_prepared_database(self):
        self.prepare()
        real_save = rescue._save
        def save(path, plan):
            if 'Installation de la base preparee' in plan['completedSteps']: raise KeyboardInterrupt()
            return real_save(path, plan)
        with patch('codex_transfer.rescue._save', side_effect=save):
            with self.assertRaises(KeyboardInterrupt): rescue.execute(self.plan)
        self.assertTrue(self.db.exists())
        self.assertEqual(rescue.execute(self.plan)['status'], 'complete')

    def test_prepare_refuses_unfinished_project_or_multiple_partials(self):
        self.j['projects'][0]['status'] = 'staged'; self.journal.write_text(json.dumps(self.j))
        with self.assertRaises(restore.RestoreError): self.prepare()
        self.j['projects'][0]['status'] = 'complete'; self.journal.write_text(json.dumps(self.j))
        rescue.temporary_for(self.rows[2][2]).write_text('another')
        with self.assertRaises(restore.RestoreError): self.prepare()

    def test_execution_does_not_reprepare_or_resolve_mappings(self):
        self.prepare()
        with patch('codex_transfer.rescue.prepare', side_effect=AssertionError('prepare repeated')), \
             patch.object(restore.PathTranslator, '__init__', side_effect=AssertionError('mapping scan')):
            self.assertEqual(rescue.execute(self.plan)['status'], 'complete')

    def test_auth_change_blocks_final_success_and_retention(self):
        self.prepare(); (self.codex / 'auth.json').write_text('changed')
        with patch('codex_transfer.recovery.enforce_retention', side_effect=AssertionError('premature cleanup')):
            with self.assertRaisesRegex(restore.RestoreError, 'authentification'): rescue.execute(self.plan)
        self.assertEqual(backup.read_json(self.journal)['status'], 'restoring')

    def test_binary_attachment_copied_once_and_reported(self):
        source = self.package / 'attachments/payload.bin'
        source.parent.mkdir(parents=True)
        source.write_bytes(bytes(range(256)) * 10000)
        mapping = self.package / 'manifest/path-mappings.json'
        mapping.write_text(json.dumps({'projects': [], 'attachments': [
            {'id': 'attach', 'originalPath': 'C:/old/payload.bin', 'sourcePresent': True,
             'backupRelativePath': 'attachments/payload.bin'}]}))
        plan = self.prepare()
        task = next(t for t in plan['tasks'] if t['kind'] == 'copy')
        rescue.execute(self.plan)
        target = Path(task['target'])
        self.assertEqual(source.read_bytes(), target.read_bytes())
        self.assertEqual(backup.read_json(self.journal)['rescue']['copiedAttachments'], 1)

    def test_long_path_and_large_line_stream_guard(self):
        target = self.codex / ('a' * 90) / ('b' * 90) / ('c' * 90) / 'long.jsonl'
        source = self.base / 'large.jsonl'; source.write_text('x' * (rescue.CHUNK * 3))
        guard = rescue.SpaceGuard()
        with patch.object(guard, 'check', wraps=guard.check) as check:
            rescue._write_task({'kind': 'rewrite', 'source': str(source), 'target': str(target)},
                               types.SimpleNamespace(text=lambda s: s), guard, lambda _: None)
        self.assertGreaterEqual(check.call_count, 6)
        self.assertEqual(target.stat().st_size, rescue.CHUNK * 3 + 1)

if __name__ == '__main__': unittest.main()
