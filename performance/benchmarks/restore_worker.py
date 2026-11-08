"""Isolated real-code benchmark worker; synthetic owned directories only.

Build this entry point separately against upstream and the completed community
sources. The final path must use RestoreOperation, including durable journals;
there is deliberately no fallback to a checkpoint-free restore.
"""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
import shutil
import tempfile
import time

from microbench import payload
from benchmark_report import PROTOCOL_VERSION, _atomic_text


def save(path, value):
    _atomic_text(path, json.dumps(value, indent=2))


def tree_hash(root):
    """Content and relative membership fingerprint; read outside timed work."""
    root = Path(root)
    result = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise RuntimeError('Unexpected link in synthetic fixture')
        if path.is_file():
            result.update(path.relative_to(root).as_posix().encode('utf-8') + b'\0')
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    result.update(block)
    return result.hexdigest()


def owned_root(path, token):
    root = Path(path).resolve()
    marker = root / '.lifeboat-benchmark-owned.json'
    if not marker.is_file() or marker.is_symlink():
        raise RuntimeError('Synthetic benchmark ownership marker is missing')
    value = json.loads(marker.read_text(encoding='utf-8'))
    if value.get('token') != token or value.get('purpose') != 'synthetic-lifeboat-benchmark':
        raise RuntimeError('Synthetic benchmark ownership marker does not match')
    return root


def isolate(root, label):
    environment = root / 'environment' / label
    for name in ('LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP'):
        path = environment / name
        path.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(path)
    tempfile.tempdir = str(environment / 'TEMP')


def profile_shape(profile, mode):
    if mode == 'quick':
        return {'small': (200, 1024, 4), 'large': (2, 1024 * 1024, 1),
                'overlap': (20, 4096, 1)}[profile]
    return {'small': (5000, 1024, 40), 'large': (8, 16 * 1024 * 1024, 1),
            'overlap': (200, 512 * 1024, 1)}[profile]


def build_fixture(root, profile, mode):
    from codex_transfer import backup, selftest
    source = root / 'source'
    if source.exists() or (root / 'fixture.json').exists():
        raise RuntimeError('Refusing to overwrite an existing synthetic fixture')
    codex, project = selftest._write_source(source)
    count, size, project_count = profile_shape(profile, mode)
    roots = [project]
    extra = []
    for number in range(1, project_count):
        path = source / 'Documents' / f'Project{number}'
        path.mkdir(parents=True)
        roots.append(path)
        extra.append({'path': str(path), 'required': True})
    for number in range(count):
        path = roots[number % len(roots)] / 'payload' / f'd{number // 100}' / f'f{number}.bin'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload(number, size, 'mixed'))
        # Fixture content and source timestamps are reproducible.
        os.utime(path, (1_600_000_000, 1_600_000_000))
    if profile == 'overlap':
        nested = project / 'nested'
        nested.mkdir()
        (nested / 'nested.txt').write_text('synthetic nested project data', encoding='utf-8')
        portable = codex / '.chatgpt-projects' / 'fixture' / 'work'
        portable.mkdir(parents=True)
        (portable / 'data.bin').write_bytes(payload(40, 700, 'mixed'))
        # The child belongs to its parent. Never manufacture an unsafe colliding
        # restore decision solely to make a timed run succeed.
        extra.append({'path': str(portable), 'required': True})
    config = root / 'config.json'
    save(config, dict(configVersion=1, includeAttachments=True, projects=extra,
                     additionalPortablePaths=[], excludeDirectoryNames=[],
                     projectRegistryPath=str(root / 'state' / 'registry.json'),
                     lineageStatePath=str(root / 'state' / 'lineage.json'),
                     deviceStatePath=str(root / 'state' / 'device.json')))
    facts = dict(profile=profile, mode=mode, added_files=count,
                 added_bytes=count * size, project_roots=len(roots) + int(profile == 'overlap'),
                 source_sha256=tree_hash(source), synthetic=True)
    save(root / 'fixture.json', facts)
    return facts


def review_synthetic_plan(root, package, target, plan, plan_api):
    """Resolve fixture conflicts through the same decision APIs as the GUI.

    This is not an unattended decision policy for user backups. Every source
    and target must belong to the freshly generated, marked synthetic fixture.
    Existing automatic decisions remain unchanged; blocking incoming items
    use their source, and destination-only items keep their target.
    """
    root, package, target = (Path(path).resolve() for path in (root, package, target))
    marker = root / '.lifeboat-benchmark-owned.json'
    if (not marker.is_file() or marker.is_symlink()
            or json.loads(marker.read_text(encoding='utf-8')).get('purpose') != 'synthetic-lifeboat-benchmark'
            or json.loads((root / 'fixture.json').read_text(encoding='utf-8')).get('synthetic') is not True):
        raise RuntimeError('Automatic decisions require an owned synthetic fixture')
    if (not package.is_relative_to(root / 'packages') or not target.is_relative_to(root / 'targets')
            or Path(str(plan.get('package', ''))).resolve() != package
            or Path(str(plan.get('targetProfile', ''))).resolve() != target):
        raise RuntimeError('Comparison plan is outside the owned synthetic trial')
    source_roots = {'project': root / 'source', 'conversation': package, 'codex': package}
    for item in plan.get('items', []):
        kind = item.get('kind')
        if kind not in source_roots:
            raise RuntimeError('Unexpected item in synthetic comparison plan')
        if item.get('source'):
            anchor = source_roots[kind]
            path = (anchor / str(item['source'])).resolve()
            if not path.is_relative_to(anchor):
                raise RuntimeError('Comparison source is outside the synthetic fixture')
        if item.get('target') and not Path(str(item['target'])).resolve().is_relative_to(target):
            raise RuntimeError('Comparison destination is outside the synthetic fixture')
    decisions = []
    for item in sorted(plan.get('items', []), key=lambda value: str(value.get('key', ''))):
        if not item.get('blocking'):
            continue
        kind = item['kind']
        decision = 'keep-source' if item.get('source') else 'keep-target'
        if kind not in ('project', 'conversation') or decision not in item.get('availableDecisions', []):
            raise RuntimeError('Synthetic conflict does not offer the expected explicit decision')
        resolve = (plan_api.resolve_project_decision if kind == 'project'
                   else plan_api.resolve_conversation_decision)
        plan = resolve(plan, item['key'], decision)
        decisions.append({'kind': kind, 'decision': decision})
    if not plan.get('ready'):
        raise RuntimeError('Synthetic comparison plan remains blocked: ' + '; '.join(
            str(reason) for reason in plan.get('blockingReasons', [])[:3]))
    return plan, decisions


def restore_trial(root, trial, variant):
    from codex_transfer import backup, restore, restore_plan, selftest
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', trial):
        raise ValueError('Invalid synthetic trial identifier')
    package_data = json.loads((root / 'fixture.json').read_text(encoding='utf-8'))
    source = root / 'source'
    if tree_hash(source) != package_data['source_sha256']:
        raise RuntimeError('Synthetic source changed before this trial')
    config = json.loads((root / 'config.json').read_text(encoding='utf-8'))
    state = root / 'state' / trial
    state.mkdir(parents=True, exist_ok=False)
    config.update(projectRegistryPath=str(state / 'registry.json'), lineageStatePath=str(state / 'lineage.json'),
                  deviceStatePath=str(state / 'device.json'))
    storage = 'archive-blocks-v1' if variant == 'final_archive' else 'files'
    if variant != 'baseline':
        config['projectStorage'] = storage
    trial_config = state / 'config.json'
    save(trial_config, config)
    backup_started = time.perf_counter()
    package = backup.build_backup(argparse.Namespace(
        config=str(trial_config), destination=str(root / 'packages' / trial),
        source_profile=str(source), source_codex_home=str(source / '.codex'), allow_running_test=False,
    ))
    backup_seconds = time.perf_counter() - backup_started
    package_description = backup.read_json(package / 'manifest' / 'package.json')
    if variant == 'final_archive' and (package_description.get('formatVersion') != '2.5'
            or package_description.get('projectStorage') != 'archive-blocks-v1'):
        raise RuntimeError('Archive worker did not create the requested production format')
    package_hash = tree_hash(package)
    if tree_hash(source) != package_data['source_sha256']:
        raise RuntimeError('Backup construction changed the synthetic source')
    target = root / 'targets' / trial
    if target.exists():
        raise RuntimeError('Each trial requires a fresh target directory')
    codex, _ = selftest._write_target(target, 'SYNTHETIC')
    original_auth = (codex / 'auth.json').read_bytes()
    original_installation = (codex / 'installation_id').read_bytes()

    # Fail closed before timing if a final worker was built without the final
    # implementation. Never label a plain baseline restore as the final build.
    operation = importlib.import_module('codex_transfer.restore_operation') if variant != 'baseline' else None
    started = time.perf_counter()
    comparison_plan = restore_plan.build_restore_plan(package, target, allow_running_test=False)
    comparison_plan, decisions = review_synthetic_plan(root, package, target, comparison_plan, restore_plan)
    planned_at = time.perf_counter()
    prepared = restore.prepare_restore(package, target, allow_running_test=False, comparison_plan=comparison_plan)
    prepared_at = time.perf_counter()
    if variant != 'baseline':
        document = operation.create_document(prepared['safetyRoot'], package, target)
        result = operation.resume_from_document(document)
        if result.get('status') != 'complete':
            raise RuntimeError('Final restore did not complete: ' + str(result.get('status')))
    else:
        result = restore.restore_backup(package, target, Path(prepared['safetyRoot']))
    elapsed = time.perf_counter() - started
    verification = result.get('verification', {})
    valid = verification.get('valid') is True
    auth_preserved = (codex / 'auth.json').read_bytes() == original_auth
    installation_preserved = (codex / 'installation_id').read_bytes() == original_installation
    checks = dict(final_verification=valid, target_authentication_preserved=auth_preserved,
                  target_installation_preserved=installation_preserved,
                  source_unchanged=tree_hash(source) == package_data['source_sha256'],
                  backup_unchanged=tree_hash(package) == package_hash)
    checkpoint = Path(prepared['safetyRoot']) / 'operation-checkpoints.sqlite'
    if variant != 'baseline':
        checks['durable_journal_created'] = checkpoint.is_file()
        checks['normal_report_retention'] = 'recoveryRetention' in result
    version = importlib.import_module('codex_transfer').__version__
    # Paths and fixture authentication data are deliberately excluded.
    return dict(kind='restore', variant=variant, protocol_version=PROTOCOL_VERSION,
                seconds=elapsed, backup_seconds=backup_seconds,
                total_seconds=backup_seconds + elapsed, project_storage=storage,
                format_version=package_description.get('formatVersion'), input_source_sha256=package_data['source_sha256'],
                plan_seconds=planned_at - started, prepare_seconds=prepared_at - planned_at,
                restore_seconds=elapsed - (prepared_at - started),
                synthetic_plan_decisions=decisions,
                valid=all(checks.values()), checks=checks,
                durable_checkpoints=variant != 'baseline', source_version=version,
                source_validation=True, final_verification=valid,
                fixture={key: package_data[key] for key in ('profile', 'mode', 'added_files', 'added_bytes', 'project_roots')},
                verification=verification.get('checks', {}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--token', required=True)
    parser.add_argument('--action', choices=['preflight', 'build', 'restore'], required=True)
    parser.add_argument('--variant', choices=['baseline', 'final', 'final_archive'], required=True)
    parser.add_argument('--profile', choices=['small', 'large', 'overlap'], default='small')
    parser.add_argument('--mode', choices=['quick', 'thorough'], default='quick')
    parser.add_argument('--trial', default='build')
    parser.add_argument('--source', help='Development-only source directory; ignored builds are forbidden')
    args = parser.parse_args(argv)
    root = owned_root(args.root, args.token)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', args.trial):
        raise ValueError('Invalid synthetic trial identifier')
    if args.source:
        if getattr(sys, 'frozen', False):
            raise ValueError('A packaged worker cannot substitute source code')
        source = Path(args.source).resolve()
        if not (source / 'codex_transfer' / 'restore.py').is_file():
            raise ValueError('Lifeboat source directory is invalid')
        sys.path.insert(0, str(source))
    isolate(root, args.trial)
    output = root / 'results' / (args.trial + '.json')
    output.parent.mkdir(exist_ok=True)
    try:
        if args.action == 'preflight':
            from codex_transfer import backup
            try:
                backup.check_codex_not_running(root / 'preflight' / '.codex', False)
            except Exception as error:
                raise RuntimeError('Fermez Codex et ChatGPT avant la comparaison complète, puis relancez. '
                                   'La garde de restauration reste active. ' + str(error)) from error
            result = {'ready': True}
        elif args.action == 'build':
            result = build_fixture(root, args.profile, args.mode)
        else:
            result = restore_trial(root, args.trial, args.variant)
        save(output, result)
        return 0 if result.get('valid', True) else 1
    except Exception as error:
        message = str(error).replace(str(root), '<synthetic>')
        if args.source:
            message = message.replace(str(Path(args.source).resolve()), '<source-code>')
        save(output, dict(valid=False, error_type=type(error).__name__, error=message))
        return 1
    finally:
        # These paths were created only for this worker's uniquely named trial.
        # Keep the shared synthetic source, marker and completed result intact.
        if args.action == 'restore':
            for parent in ('targets', 'packages', 'state'):
                path = root / parent / args.trial
                if path.exists():
                    shutil.rmtree(path)


if __name__ == '__main__':
    raise SystemExit(main())
