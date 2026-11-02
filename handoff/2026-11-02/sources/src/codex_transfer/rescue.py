"""Targeted rescue of a 3.4.7 restore stopped inside _restore_sessions.

No preflight, project walks, portable-profile recopy or rollback. The plan is
local operational state: keep it with the original recovery point, not in git.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import errno
import json
import os
import shutil
import sqlite3
import time
import traceback
from pathlib import PurePosixPath
from typing import Callable

from .fs_paths import Path, sqlite_uri
from . import atomic_io, backup, lineage, project_identity, recovery, restore, windows
from . import rollout

VERSION = 1
RESERVE = 500_000_000  # 500 Mo, decimal; preparation is exempt.
CHUNK = 1024 * 1024


class SpacePause(RuntimeError):
    pass


def temporary_for(destination: Path) -> Path:
    return destination.with_name('.' + destination.name + '.restore.tmp' +
                                 ('.jsonl.zst' if rollout.is_compressed(destination) else '.jsonl'))


class SpaceGuard:
    def __init__(self, reserve=RESERVE):
        self.reserve = reserve

    def check(self, path: Path, pending=0):
        probe = path if path.is_dir() else path.parent
        while not probe.exists():
            probe = probe.parent
        free = shutil.disk_usage(probe).free
        if free <= self.reserve + pending:
            raise SpacePause(f'Espace insuffisant : {free / 1_000_000:.1f} Mo libres ; '
                             f'reserve {self.reserve / 1_000_000:.0f} Mo. Liberez de l’espace puis reprenez.')


def _save(path, plan):
    plan['updatedAtUtc'] = backup.utc_now()
    atomic_io.write_json(path, plan)


def _read_only_counts(database):
    with contextlib.closing(sqlite3.connect(sqlite_uri(database), uri=True)) as db:
        check = backup.sqlite_quick_check(db)
        if check != 'ok':
            raise restore.RestoreError(f'Base temporaire invalide : {check}')
        return {'finalThreads': db.execute('SELECT count(*) FROM threads').fetchone()[0]}


def _translator_state(translator):
    return {
        'source_profile': str(translator.source_profile),
        'target_profile': str(translator.target_profile),
        'package_root': str(translator.package_root),
        'project_targets': {k: str(v) for k, v in translator.project_targets.items()},
        'attachment_targets': {k: str(v) for k, v in translator.attachment_targets.items()},
        'approved_external_roots': [str(p) for p in translator.approved_external_roots],
        'replacements': translator.replacements,
        'mappings': translator.mappings,
    }


def _load_translator(state):
    # Use prepared mappings; no new location resolution or inventory at execution.
    obj = restore.PathTranslator.__new__(restore.PathTranslator)
    for name in ('source_profile', 'target_profile', 'package_root'):
        setattr(obj, name, Path(state[name]))
    for name in ('project_targets', 'attachment_targets'):
        setattr(obj, name, {k: Path(v) for k, v in state[name].items()})
    obj.approved_external_roots = tuple(Path(p) for p in state['approved_external_roots'])
    obj.replacements = state['replacements']
    obj.mappings = state['mappings']
    return obj


def prepare(journal_path: Path, log_path: Path, plan_path: Path,
            progress: Callable[[str], None] = lambda _: None):
    """One-time metadata-only preparation. Never guarded by the 500 MB threshold."""
    journal_path, log_path, plan_path = map(Path, (journal_path, log_path, plan_path))
    if plan_path.exists():
        raise restore.RestoreError('Le plan existe deja : chargez-le ou choisissez un autre nom.')
    journal = backup.read_json(journal_path)
    if journal.get('status') != 'restoring':
        raise restore.RestoreError('Cette reprise exige le journal interrompu au statut restoring.')
    if journal.get('targetThreadsBefore') != 0 or journal.get('targetProjectsBefore') != 0:
        raise restore.RestoreError('Outil reserve a cette restauration vers un profil initialement vide.')
    if journal.get('approvedExternalRoots'):
        raise restore.RestoreError('Cette version de secours ne traite pas les racines externes.')
    projects = journal.get('projects', [])
    if not projects or any(p.get('status') != 'complete' for p in projects):
        raise restore.RestoreError('Tous les groupes de projets doivent avoir termine dans le journal.')
    for item in (journal.get('comparisonPlan') or {}).get('items', []):
        if item.get('proposedAction') in ('retain', 'keep-both', 'archive', 'delete-project', 'archive-and-replace'):
            raise restore.RestoreError('Decision de conservation/conflit hors du perimetre de ce secours.')
    # Read only the tail of the supplied GUI log, not millions of validation lines.
    with log_path.open('rb') as handle:
        handle.seek(max(0, log_path.stat().st_size - 256 * 1024))
        tail = handle.read().decode('utf-8-sig', errors='replace')
    if not all(token in tail for token in ('_restore_sessions', '_rewrite_copy', 'No space left on device',
                                           'Replacing local portable Codex user data')):
        raise restore.RestoreError('La trace ne confirme pas l’arret attendu dans la copie des conversations.')
    if 'running automatic rollback' in tail or 'Rollback completed' in tail:
        raise restore.RestoreError('Un rollback est mentionne : cette reprise directe ne convient pas.')
    package = Path(journal['package'])
    profile = Path(journal['targetProfile'])
    safety = journal_path.parent
    codex = profile / '.codex'
    database = safety / 'state_5.restored.tmp.sqlite'
    progress('Lecture du journal et de la base deja preparee...')
    counts = _read_only_counts(database)
    translator = restore.PathTranslator(package, profile)
    sessions_root = codex / 'sessions'
    partials = list(sessions_root.rglob('*.restore.tmp*'))
    if len(partials) != 1:
        raise restore.RestoreError(f'Un seul fichier interrompu attendu ; trouves : {len(partials)}.')
    partial = partials[0]
    tasks, reused = [], []
    partial_matched = False
    progress('Inventaire des conversations uniquement (aucun parcours des projets)...')
    for folder in ('sessions', 'archived_sessions'):
        source_root = package / 'codex' / folder
        for source in rollout.iter_files(source_root):
            destination = codex / folder / source.relative_to(source_root)
            is_partial = temporary_for(destination) == partial
            partial_matched |= is_partial
            # _restore_sessions removes sessions before starting and commits each
            # file with os.replace. Presence proves completion in this incident.
            # rglob order is NOT stable: never infer a lexical resume position.
            if folder == 'sessions' and destination.is_file() and not is_partial:
                reused.append(str(destination))
            else:
                tasks.append({'kind': 'rewrite', 'source': str(source),
                              'target': str(destination), 'status': 'pending',
                              'bytes': source.stat().st_size})
    if not partial_matched:
        raise restore.RestoreError('Le fichier interrompu ne correspond a aucune conversation source.')
    tasks.sort(key=lambda task: (temporary_for(Path(task['target'])) != partial, task['target']))
    # Source index would immediately be rebuilt: generate it once from final DB.
    for item in translator.mappings.get('attachments', []):
        if item.get('sourcePresent'):
            source = package / Path(*PurePosixPath(item['backupRelativePath']).parts)
            tasks.append({'kind': 'copy', 'source': str(source),
                          'target': str(translator.attachment_targets[str(item['id'])]),
                          'status': 'pending', 'bytes': source.stat().st_size})
    plan = {
        'format': 'lifeboat-targeted-rescue', 'version': VERSION,
        'createdAtUtc': backup.utc_now(), 'status': 'prepared',
        'originalFailureTail': tail[-12000:],
        'journalPath': str(journal_path.resolve()), 'journal': journal,
        'package': str(package), 'profile': str(profile), 'safety': str(safety),
        'database': str(database), 'databaseCounts': counts,
        'translator': _translator_state(translator), 'tasks': tasks,
        'reusedSessions': reused, 'interruptedFile': str(partial),
        'completedSteps': [], 'reserveBytes': RESERVE,
        'authHash': backup.sha256_file(codex / 'auth.json'),
        'reportPath': str(windows.documents_folder(profile) / 'Codex Restore Reports' /
                          ('rescue-' + safety.name + '.json')),
        'verificationScope': 'Prior project validation reused; no repeated tree/hash/portability audit.',
    }
    _save(plan_path, plan)
    progress(f'Plan enregistre : {len(reused)} conversations conservees, '
             f'{sum(t["kind"] == "rewrite" for t in tasks)} a terminer, '
             f'{sum(t["kind"] == "copy" for t in tasks)} pieces jointes a copier.')
    return plan


def _write_task(task, translator, guard, progress):
    source, target = Path(task['source']), Path(task['target'])
    guard.check(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = temporary_for(target)
    written = 0
    next_update = time.monotonic()
    def write_chunks(writer, value):
        nonlocal written, next_update
        for offset in range(0, len(value), CHUNK):
            part = value[offset:offset + CHUNK]
            # Reserve for UTF-8 expansion and buffered/compressed writer output.
            guard.check(target, len(part) * (4 if isinstance(part, str) else 1) + 65536)
            writer.write(part)
            written += len(part)
            if time.monotonic() >= next_update:
                progress(f'{target.name} : {written / 1_000_000:.1f} Mo traites')
                next_update = time.monotonic() + 1
    if task['kind'] == 'rewrite':
        with rollout.open_text(source, errors='replace', newline='') as reader:
            with rollout.open_text_writer(temporary) as writer:
                parts, buffered = [], 0
                for line in reader:
                    value = translator.text(line.rstrip('\r\n')) + '\n'
                    parts.append(value)
                    buffered += len(value)
                    if buffered >= CHUNK:
                        write_chunks(writer, ''.join(parts))
                        parts, buffered = [], 0
                if parts:
                    write_chunks(writer, ''.join(parts))
                guard.check(target, 65536)
    else:
        with source.open('rb') as reader, temporary.open('wb') as writer:
            while chunk := reader.read(CHUNK):
                write_chunks(writer, chunk)
            writer.flush()
            os.fsync(writer.fileno())
    # Flush compressed footer before fsync and atomic commit.
    with temporary.open('rb+') as handle:
        os.fsync(handle.fileno())
    guard.check(target)
    os.replace(temporary, target)
    atomic_io._sync_parent(target.parent)


@contextlib.contextmanager
def _exclusive(safety):
    path = Path(safety) / 'rescue.lock'
    with path.open('a+b') as handle:
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            if path.stat().st_size == 0:
                handle.write(b'0'); handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise restore.RestoreError('Une autre reprise est deja ouverte.') from exc
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def execute(plan_path: Path, progress: Callable[[str], None] = lambda _: None):
    plan_path = Path(plan_path)
    plan = backup.read_json(plan_path)
    if plan.get('format') != 'lifeboat-targeted-rescue' or plan.get('version') != VERSION:
        raise restore.RestoreError('Format de plan non reconnu.')
    if plan['status'] == 'complete':
        progress('Cette reprise est deja terminee.')
        return plan
    with _exclusive(plan['safety']):
        # Reload under lock; no inventory, hash scan or preparation repeated.
        plan = backup.read_json(plan_path)
        if plan['status'] == 'complete':
            return plan
        try:
            return _execute(plan_path, plan, progress)
        except Exception as exc:
            plan['status'] = 'paused-space' if isinstance(exc, SpacePause) or (
                isinstance(exc, OSError) and (exc.errno == errno.ENOSPC or getattr(exc, 'winerror', None) == 112)
            ) else 'interrupted'
            plan['lastError'] = {'message': str(exc), 'traceback': traceback.format_exc(), 'at': backup.utc_now()}
            try:
                _save(plan_path, plan)
            except Exception as save_error:
                progress(f'Le dernier point enregistre reste utilisable. Echec journal : {save_error}')
            # Never invoke rollback. Never mask the original exception.
            raise


def _execute(plan_path, plan, progress):
    guard = SpaceGuard(RESERVE)
    profile, package, safety = (Path(plan[k]) for k in ('profile', 'package', 'safety'))
    codex = profile / '.codex'
    guard.check(codex)
    guard.check(plan_path)
    translator = _load_translator(plan['translator'])
    journal = plan['journal']
    comparison = journal.get('comparisonPlan')
    plan['status'] = 'running'
    plan.pop('lastError', None)
    _save(plan_path, plan)
    for number, task in enumerate(plan['tasks'], 1):
        if task['status'] == 'done':
            continue
        plan['current'] = task['target']
        progress(f'Fichier restant {number}/{len(plan["tasks"])} : {task["target"]}')
        _write_task(task, translator, guard, progress)
        task['status'] = 'done'
        _save(plan_path, plan)

    def step(name, action):
        if name in plan['completedSteps']:
            return
        guard.check(codex)
        guard.check(plan_path)
        progress(name)
        plan['current'] = name
        result = action()
        if result is not None:
            plan.setdefault('results', {})[name] = result
        plan['completedSteps'].append(name)
        _save(plan_path, plan)

    step('Parametres portables', lambda: restore._restore_global_state(package, codex, translator, comparison))

    def install_database():
        database = Path(plan['database'])
        # Retain prepared DB as restart evidence. Copy just ~4 MiB atomically;
        # unlike a move, crash between replacement and checkpoint is retryable.
        for suffix in ('-wal', '-shm'):
            (codex / ('state_5.sqlite' + suffix)).unlink(missing_ok=True)
        _write_task({'kind': 'copy', 'source': str(database), 'target': str(codex / 'state_5.sqlite')},
                    translator, guard, progress)
    step('Installation de la base preparee', install_database)
    step('Index des conversations', lambda: restore._rebuild_session_index(codex / 'state_5.sqlite', codex))

    def verify():
        if backup.sha256_file(codex / 'auth.json') != plan['authHash']:
            raise restore.RestoreError('L’authentification locale a change depuis la preparation.')
        result = restore.verify_restored(package, profile, translator, comparison,
                                         reuse_project_evidence=journal['projects'])
        if not result['valid']:
            raise restore.RestoreError('; '.join(result['errors'][:10]))
        return result
    step('Verification finale ciblee', verify)

    def identities():
        path = package / 'manifest/project-identities.json'
        if not path.is_file():
            return 0
        manifest = backup.read_json(path)
        registry_path = windows.project_registry_path(profile)
        registry = project_identity.load_registry(registry_path)
        project_identity.register_restored_roots(registry, manifest, translator.project_targets)
        restore._remove_dispositioned_identity_roots(registry, comparison)
        project_identity.save_registry(registry_path, registry)
        return len(manifest.get('roots', []))
    step('Registre des projets', identities)

    def register_lineage():
        source = package / 'manifest/lineage.json'
        target = windows.lineage_state_path(profile)
        if source.is_file():
            lineage.save_state(target, lineage.state_from_manifest(backup.read_json(source)))
            return True
        target.unlink(missing_ok=True)
        return False
    step('Historique de sauvegarde', register_lineage)

    def complete_journal():
        journal.update({
            'status': 'complete', 'completedAtUtc': backup.utc_now(),
            'databaseCounts': plan['databaseCounts'],
            'recentIndexEntries': plan['results']['Index des conversations'],
            'verification': plan['results']['Verification finale ciblee'],
            'projectIdentitiesRegistered': plan['results']['Registre des projets'],
            'lineageRegistered': plan['results']['Historique de sauvegarde'],
            'pathMappings': plan['translator']['project_targets'],
            'rescue': {'plan': str(plan_path), 'preparedAtUtc': plan['createdAtUtc'],
                       'reusedSessions': len(plan['reusedSessions']),
                       'copiedSessions': sum(t['kind'] == 'rewrite' for t in plan['tasks']),
                       'copiedAttachments': sum(t['kind'] == 'copy' for t in plan['tasks']),
                       'reusedProjectGroups': len(journal['projects']),
                       'verificationScope': plan['verificationScope'],
                       'interruptedFile': plan['interruptedFile']},
        })
        backup.write_json(Path(plan['journalPath']), journal)
        backup.write_json(Path(plan['reportPath']), journal)
    step('Journal et rapport de restauration', complete_journal)

    def retention():
        # Same conservative native retention after success only.
        try:
            result = recovery.enforce_retention(profile, keep=recovery.DEFAULT_KEEP, progress=progress)
            journal['recoveryRetention'] = result
        except Exception as exc:
            journal['recoveryRetentionError'] = f'{type(exc).__name__}: {exc}'
        backup.write_json(Path(plan['journalPath']), journal)
        backup.write_json(Path(plan['reportPath']), journal)
    step('Archivage des points de recuperation', retention)
    plan['status'] = 'complete'
    plan['completedAtUtc'] = backup.utc_now()
    _save(plan_path, plan)
    progress('Restauration terminee. Rapport : ' + plan['reportPath'])
    return plan
