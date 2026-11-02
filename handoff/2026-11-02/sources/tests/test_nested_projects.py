import csv
from contextlib import closing
import argparse
import hashlib
import json
import os
from codex_transfer.fs_paths import Path
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

# Windows APIs are not invoked by these isolated filesystem tests on Linux.
if os.name != 'nt':
    sys.modules.setdefault('winreg', types.ModuleType('winreg'))
from codex_transfer import location_mapper, nested_projects, restore


class NestedProjectsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.package = self.base / 'backup'
        self.profile = self.base / 'destination'
        self.safety = self.profile / 'AppData/Local/Codex Lifeboat/recovery-points/test'
        (self.package / 'manifest').mkdir(parents=True)
        (self.safety / 'codex-before-restore').mkdir(parents=True)
        (self.safety / 'codex-before-restore/auth.json').write_text('untouched')
        self.paths = ['Workspace', 'Workspace/Legal', 'Workspace/Social', 'Workspace/Social/Studio']
        tree = {'README': b'root', 'Legal/note': b'law', 'Social/post': b'post', 'Social/Studio/movie': b'video'}
        self.projects = []
        self.mappings = []
        for i, relative in enumerate(self.paths):
            key = str(i)
            prefix = 'projects/root-' + key
            source = self.package / prefix
            source.mkdir(parents=True)
            subtree = relative[len('Workspace'):].strip('/')
            selected = {k[len(subtree)+1:] if subtree else k: v for k, v in tree.items() if not subtree or k.startswith(subtree + '/')}
            for name, data in selected.items():
                file = source / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(data)
            self.projects.append({'id': key, 'backupRelativePath': prefix, 'fileCount': len(selected), 'totalBytes': sum(map(len, selected.values()))})
            self.mappings.append({'id': key, 'sourcePresent': True, 'originalPath': 'C:/Users/source/Documents/' + relative,
                'location': {'schemaVersion': 1, 'kind': 'known-folder', 'knownFolder': 'documents', 'relativePath': relative, 'logicalPath': 'known-folder://documents/' + relative, 'originalPath': 'C:/Users/source/Documents/' + relative, 'requiresTargetMapping': False}})
        self.write_manifests()
        self.journal = {'projects': []}
        self.translator = types.SimpleNamespace(target_profile=self.profile, external_roots={}, approved_external_roots=(),
            project_targets={str(i): self.profile / 'Documents' / p for i, p in enumerate(self.paths)})
        # Only portable-path resolution needs adapting to a POSIX test host.
        if os.name != 'nt':
            adapter = patch('codex_transfer.path_model.resolve_portable_location',
                side_effect=lambda loc, profile, folders, *args: Path(folders['documents']) / loc['relativePath'])
            adapter.start()
            self.addCleanup(adapter.stop)

    def write_manifests(self):
        (self.package / 'manifest/projects.json').write_text(json.dumps(self.projects))
        (self.package / 'manifest/path-mappings.json').write_text(json.dumps({'mappingVersion': 2, 'projects': self.mappings}))
        with (self.package / 'manifest/sha256.csv').open('w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['relative_path', 'size', 'sha256'])
            for project in self.projects:
                for file in sorted((self.package / project['backupRelativePath']).rglob('*')):
                    if file.is_file():
                        data = file.read_bytes()
                        writer.writerow([file.relative_to(self.package).as_posix(), len(data), hashlib.sha256(data).hexdigest()])

    def plan(self):
        return location_mapper.build_plan(self.mappings, self.profile, {}, self.package)

    def review(self, actions):
        return {'locationPlan': self.plan(), 'items': [{'key': 'project/' + str(i), 'kind': 'project', 'source': self.mappings[i]['originalPath'],
            'target': str(self.translator.project_targets[str(i)]), 'proposedAction': action} for i, action in enumerate(actions)]}

    def test_four_collisions_become_one_group(self):
        plan = self.plan()
        self.assertTrue(plan['ready'], plan['issues'])
        self.assertEqual(plan['nestedProjects']['parents'], {'1': '0', '2': '0', '3': '0'})

    def test_arbitrary_manifest_order(self):
        self.mappings.reverse()
        self.projects.reverse()
        self.write_manifests()
        restore._restore_projects(self.package, self.safety, self.translator, self.journal, None)
        self.assertEqual(len(self.journal['projects']), 1)
        self.assertEqual(self.journal['projects'][0]['id'], '0')

    def test_single_transaction_and_exact_child_verification(self):
        before = {p.relative_to(self.package): p.read_bytes() for p in self.package.rglob('*') if p.is_file()}
        copied = restore._restore_projects(self.package, self.safety, self.translator, self.journal, None)
        self.assertEqual(copied, 4)
        self.assertEqual(len(self.journal['projects']), 1)
        for project in self.projects:
            restore._verify_staged_project(self.package, project, self.translator.project_targets[project['id']])
        self.assertEqual(before, {p.relative_to(self.package): p.read_bytes() for p in self.package.rglob('*') if p.is_file()})

    def test_rollback_after_activation_restores_original_group(self):
        target = self.translator.project_targets['0']
        target.mkdir(parents=True)
        (target / 'old').write_text('original')
        with self.assertRaisesRegex(restore.RestoreError, 'Intentional failure'):
            restore._restore_projects(self.package, self.safety, self.translator, self.journal, None, fail_after_activation_for_test=True)
        restore.rollback_restore(self.safety, self.profile)
        self.assertEqual([p.name for p in target.iterdir()], ['old'])
        self.assertEqual((target / 'old').read_text(), 'original')

    def test_rollback_after_quarantine_restores_original_group(self):
        target = self.translator.project_targets['0']
        target.mkdir(parents=True)
        (target / 'old').write_text('original')
        with self.assertRaisesRegex(restore.RestoreError, 'Intentional failure'):
            restore._restore_projects(self.package, self.safety, self.translator, self.journal, None, fail_after_quarantine_for_test=True)
        restore.rollback_restore(self.safety, self.profile)
        self.assertEqual((target / 'old').read_text(), 'original')

    def test_divergent_snapshots_block_before_writes(self):
        (self.package / 'projects/root-3/movie').write_bytes(b'other')
        self.write_manifests()
        plan = self.plan()
        self.assertFalse(plan['ready'])
        self.assertIn('Nested snapshots differ', str(plan['issues']))
        with self.assertRaises(restore.RestoreError):
            restore._restore_projects(self.package, self.safety, self.translator, self.journal, None)
        self.assertFalse(self.translator.project_targets['0'].exists())
        self.assertEqual(self.journal['projects'], [])

    def test_child_extra_file_blocks(self):
        (self.package / 'projects/root-3/new').write_bytes(b'extra')
        self.projects[3]['fileCount'] += 1
        self.projects[3]['totalBytes'] += 5
        self.write_manifests()
        self.assertFalse(self.plan()['ready'])

    def test_equal_destinations_still_block(self):
        self.mappings[1]['location']['relativePath'] = 'Workspace'
        self.assertFalse(self.plan()['ready'])

    def test_unrelated_sources_mapped_inside_parent_still_block(self):
        self.mappings[1]['originalPath'] = 'D:/unrelated'
        self.assertFalse(self.plan()['ready'])

    def test_missing_manifest_fails_closed(self):
        (self.package / 'manifest/sha256.csv').unlink()
        self.assertFalse(self.plan()['ready'])

    def test_review_cannot_keep_child_while_replacing_parent(self):
        review = self.review(['replace', 'create', 'create', 'retain'])
        self.assertTrue(nested_projects.decision_errors(review))
        with self.assertRaisesRegex(restore.RestoreError, 'compatible decisions'):
            restore._restore_projects(self.package, self.safety, self.translator, self.journal, None, review)
        self.assertEqual(self.journal['projects'], [])

    def test_compatible_review_creates_group(self):
        review = self.review(['create'] * 4)
        self.assertFalse(nested_projects.decision_errors(review))
        restore._restore_projects(self.package, self.safety, self.translator, self.journal, None, review)
        self.assertEqual(len(self.journal['projects']), 1)

    def test_corrupt_parent_payload_rejected_before_activation(self):
        (self.package / 'projects/root-0/README').write_bytes(b'bad!')
        with self.assertRaisesRegex(restore.RestoreError, 'hash differs'):
            restore._restore_projects(self.package, self.safety, self.translator, self.journal, None)
        self.assertFalse(self.translator.project_targets['0'].exists())


@unittest.skipUnless(os.name == "nt", "Full Codex backup/restore requires Windows")
class WindowsRoundTripTest(unittest.TestCase):
    def test_backup_restore_verify_with_nested_database_roots(self):
        self.round_trip(False)

    def test_long_paths_backup_restore_verify_and_rollback(self):
        self.round_trip(True)

    @__import__("contextlib").contextmanager
    def cleanup_deep(self, directory):
        try:
            yield
        finally:
            shutil.rmtree(Path(directory))

    def round_trip(self, long_paths):
        from codex_transfer import backup, selftest, restore_plan
        from codex_transfer.validate import validate
        with tempfile.TemporaryDirectory() as td, self.cleanup_deep(td):
            root = Path(td).resolve()
            if long_paths:
                root = root / ("long-directory-" * 8) / ("nested-directory-" * 8)
                root.mkdir(parents=True)
                self.assertGreater(len(str(root)), 260)
            source = root / "source-user"
            destination = root / "target-user"
            codex, project = selftest._write_source(source)
            _, old_project = selftest._write_target(destination, "NESTED")
            children = [project / "Legal", project / "Social", project / "Social/Studio"]
            with closing(sqlite3.connect(codex / "state_5.sqlite")) as conn, conn:
                for i, child in enumerate(children):
                    child.mkdir(parents=True, exist_ok=True)
                    (child / (str(i) + ".txt")).write_text("nested-" + str(i))
                    key = "nested-project-" + str(i)
                    conn.execute("INSERT INTO projects VALUES(?,?,?,?,?,?)", (key, child.name, "{}", i + 1, 1, 1))
                    conn.execute("INSERT INTO project_roots VALUES(?,?,?)", (key, 0, str(child)))
            config = root / "config.json"
            config.write_text(json.dumps({"configVersion": 1, "destinationRoot": str(root / "usb"),
                "includeAttachments": True, "projects": [], "additionalPortablePaths": [], "excludeDirectoryNames": [],
                "projectRegistryPath": str(root / "state/projects.json"), "lineageStatePath": str(root / "state/lineage.json"),
                "deviceStatePath": str(root / "state/device.json")}))
            package = backup.build_backup(argparse.Namespace(config=str(config), destination=str(root / "usb"),
                source_profile=str(source), source_codex_home=str(codex), allow_running_test=True))
            self.assertTrue(validate(package, True)["valid"])
            manifest_before = selftest._hash_tree(package)
            review = restore_plan.build_restore_plan(package, destination, allow_running_test=True)
            for item in list(review["items"]):
                if item.get("blocking"):
                    resolver = restore_plan.resolve_project_decision if item["kind"] == "project" else restore_plan.resolve_conversation_decision
                    review = resolver(review, item["key"], "keep-source")
            self.assertTrue(review["ready"], review["blockingReasons"])
            prepared = restore.prepare_restore(package, destination, allow_running_test=True, comparison_plan=review)
            safety = Path(prepared["safetyRoot"])
            result = restore.restore_backup(package, destination, safety)
            self.assertTrue(result["verification"]["valid"], result["verification"])
            self.assertEqual(len(result["projects"]), 1)
            with closing(sqlite3.connect(destination / ".codex/state_5.sqlite")) as conn:
                roots = dict(conn.execute("SELECT project_id,path FROM project_roots"))
                for i, child in enumerate(children):
                    self.assertEqual(Path(roots["nested-project-" + str(i)]), old_project / child.relative_to(project))
            self.assertEqual(manifest_before, selftest._hash_tree(package))
            restore.rollback_restore(safety, destination)
            self.assertEqual((old_project / "OLD.txt").read_text(), "NESTED")


if __name__ == '__main__':
    unittest.main()
