"""Windows benchmark launcher and repeatable baseline/final campaign.

The UI is optional. CLI runs use the same engine and preserve partial reports
on Ctrl+C. No benchmark entry point accepts a personal backup or restore target.
"""
import argparse
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from benchmark_report import CACHE_NOTE, DEFENDER_REMINDER, PROTOCOL_VERSION, defender_state, save_report, utc_now


UPSTREAM = '4fe9724ccb54422455544e56b54399fa2bc94bc3'
LIMITATIONS = [
    'Données synthétiques : aucune extrapolation aux 88 Gio ou aux cinq millions de fichiers.',
    CACHE_NOTE,
    'La génération des données est exclue ; le backup est mesuré séparément puis ajouté au total.',
    'Plan comparatif et contrôles de fermeture du parcours GUI inclus ; attente humaine exclue.',
    'Ce protocole remplace les mesures antérieures qui omettaient le plan comparatif et des gardes communes.',
    'Les contrôles initiaux et finaux restent actifs ; la version finale inclut ses checkpoints durables.',
    'Des empreintes de contenu/appartenance des fichiers sont vérifiées hors chrono et peuvent réchauffer le cache.',
    'Les microtests ZIP et copie sans métadonnées n’ont pas la fidélité d’une restauration complète.',
    'Les observations de Defender aux limites des essais ne prouvent pas un état constant entre elles.',
    'Un test rapide est exploratoire ; les petits écarts et essais brefs sont sensibles au bruit.',
]


class StopAfterTrial(Exception):
    pass


class Cancelled(Exception):
    pass


@dataclass
class RunControl:
    stop_after_trial: threading.Event = field(default_factory=threading.Event)
    cancel: threading.Event = field(default_factory=threading.Event)


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def source_hash(root):
    """Identify the code actually imported, including uncommitted final changes."""
    root = Path(root)
    digest = hashlib.sha256()
    paths = sorted((root / 'codex_transfer').rglob('*.py'))
    if not paths:
        raise ValueError('No Lifeboat Python source was found')
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode('utf-8') + b'\0')
        digest.update(path.read_bytes())
    return digest.hexdigest()


def baseline_provenance(source):
    """Verify a pinned clean checkout when available; never invent provenance."""
    source = Path(source).resolve()
    result = {'reference_upstream_commit': UPSTREAM, 'verified_upstream': False,
              'origin': 'provided-source-origin-unverified'}
    try:
        commit = subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD'], capture_output=True,
                                text=True, check=True, timeout=10).stdout.strip()
        changed = subprocess.run(['git', '-C', str(source), 'status', '--porcelain', '--', '.'],
                                 capture_output=True, text=True, check=True, timeout=10).stdout.strip()
        result['observed_git_commit'] = commit
        if commit == UPSTREAM and not changed:
            result.update(verified_upstream=True, origin='pinned-clean-upstream-checkout', upstream_commit=commit)
    except (OSError, subprocess.SubprocessError):
        pass
    return result


class WorkerPair:
    """Two different processes with independently selected source packages."""
    def __init__(self, baseline_source=None, final_source=None, executable_directory=None):
        if bool(baseline_source) != bool(final_source):
            raise ValueError('Both baseline and final source directories are required')
        self.sources = None
        self.directory = Path(executable_directory or Path(sys.executable).parent)
        self.build = None
        if baseline_source:
            if getattr(sys, 'frozen', False):
                raise ValueError('Packaged benchmarks cannot substitute source directories')
            self.sources = {'baseline': Path(baseline_source).resolve(), 'final': Path(final_source).resolve()}
            if self.sources['baseline'] == self.sources['final']:
                raise ValueError('Baseline and final must be different source directories')
            for path in self.sources.values():
                if not (path / 'codex_transfer' / 'restore.py').is_file():
                    raise ValueError('Invalid Lifeboat source directory')
        else:
            manifest = self.directory / 'BENCHMARK-BUILD.json'
            if not manifest.is_file():
                raise RuntimeError('Extract the complete benchmark ZIP: BENCHMARK-BUILD.json is missing')
            self.build = json.loads(manifest.read_text(encoding='utf-8'))

    def command(self, variant):
        variant = 'baseline' if variant == 'baseline' else 'final'
        if self.sources:
            return [sys.executable, str(Path(__file__).with_name('restore_worker.py')),
                    '--source', str(self.sources[variant])]
        return [str(self.directory / ('Lifeboat-Baseline-Worker.exe' if variant == 'baseline' else 'Lifeboat-Final-Worker.exe'))]

    def identity(self):
        if self.sources:
            hashes = {variant: source_hash(path) for variant, path in self.sources.items()}
            if hashes['baseline'] == hashes['final']:
                raise ValueError('Baseline and final source contents are identical')
            return {'type': 'separate-source-processes', 'baseline_provenance': baseline_provenance(self.sources['baseline']),
                    'source_sha256': hashes}
        workers = {}
        for variant in ('baseline', 'final'):
            path = Path(self.command(variant)[0])
            actual = file_hash(path)
            expected = self.build.get('workers', {}).get(variant, {}).get('sha256')
            if not expected or actual.lower() != expected.lower():
                raise RuntimeError('Benchmark worker identity mismatch: ' + variant)
            workers[variant] = {'sha256': actual}
        return {'type': 'separate-packaged-processes', 'build': self.build, 'verified_workers': workers}


def _terminate(process):
    if process.poll() is None:
        if os.name == 'nt':
            # PyInstaller onefile has a bootstrap parent and a child. Stop only
            # this owned worker's process tree, so no writer outlives cleanup.
            taskkill = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'taskkill.exe'
            subprocess.run([str(taskkill), '/PID', str(process.pid), '/T', '/F'],
                           capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def run_worker(pair, variant, root, token, action, trial, profile, mode, control, timeout=1800):
    command = pair.command(variant) + ['--root', str(root), '--token', token, '--action', action,
                '--trial', trial, '--profile', profile, '--mode', mode, '--variant', variant]
    log = root / (trial + '.log')
    flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if os.name == 'nt' else 0
    if control.cancel.is_set():
        raise Cancelled()
    with log.open('w', encoding='utf-8') as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT, creationflags=flags)
        started = time.monotonic()
        try:
            while process.poll() is None:
                if control.cancel.wait(.15):
                    raise Cancelled()
                if time.monotonic() - started > timeout:
                    raise TimeoutError('Synthetic worker exceeded its time limit')
        finally:
            _terminate(process)
    result_path = root / 'results' / (trial + '.json')
    if not result_path.is_file():
        tail = log.read_text(encoding='utf-8', errors='replace')[-2000:]
        tail = tail.replace(str(root), '<synthetic>')
        if pair.sources:
            for path in pair.sources.values():
                tail = tail.replace(str(path), '<source-code>')
        raise RuntimeError('Benchmark worker returned no result: ' + tail)
    result = json.loads(result_path.read_text(encoding='utf-8'))
    if process.returncode or result.get('valid') is False:
        raise RuntimeError(result.get('error', 'Synthetic restoration failed its integrity checks'))
    return result


def _boundary(control):
    if control.cancel.is_set():
        raise Cancelled()
    if control.stop_after_trial.is_set():
        raise StopAfterTrial()


def _safe_error(error, owned=None, sources=None):
    text = type(error).__name__ + ': ' + str(error)
    if owned:
        text = text.replace(str(owned), '<synthetic>')
    for path in (sources or {}).values():
        text = text.replace(str(path), '<source-code>')
    return text


def run_suite(directory, mode='quick', repeats=None, focus='all', baseline_source=None,
              final_source=None, control=None, observer=None, worker_pair=None,
              state_reader=None, include_archives=False):
    if mode not in ('quick', 'thorough') or focus not in ('all', 'restore', 'io'):
        raise ValueError('Unknown benchmark mode or scope')
    repeats = (1 if mode == 'quick' else 3) if repeats is None else repeats
    if (mode == 'quick' and repeats != 1) or (mode == 'thorough' and not 2 <= repeats <= 5):
        raise ValueError('Quick mode uses one repetition; thorough mode accepts two to five')
    control = control or RunControl()
    state_reader = state_reader or defender_state
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ('benchmark-lifeboat-' + str(time.time_ns()) + '.json')
    restore_profiles = ['small', 'large'] if mode == 'quick' else ['small', 'large', 'overlap']
    io_profiles = ['mixed'] if mode == 'quick' else ['mixed', 'incompressible', 'compressible']
    variants = ('baseline', 'final', 'final_archive') if include_archives else ('baseline', 'final')
    planned = (len(restore_profiles) * len(variants) * repeats if focus != 'io' else 0)
    planned += (len(io_profiles) * 6 * repeats if focus != 'restore' else 0)
    report = dict(schema=4, kind='lifeboat-benchmark-suite', protocol_version=PROTOCOL_VERSION, started_at=utc_now(),
                  mode=mode, repeats=repeats, focus=focus, platform=platform.platform(),
                  python=platform.python_version(), status='running', passed=False,
                  planned_trials=planned, trials=[], fixtures=[], archive_setup=[], errors=[],
                  include_archives=include_archives and focus != 'io',
                  limitations=list(LIMITATIONS), cache_controlled=False, defender_samples=[])
    owned = None
    pair = worker_pair

    def publish(message=None):
        if message is not None:
            report['current_activity'] = message
        save_report(path, report)
        if observer:
            observer(report, path)

    def record_defender(state, label):
        if state.get('status') == 'ok' and 'available' not in state:
            state = dict(state, available=True)
        report['defender_samples'].append({'at': utc_now(), 'boundary': label, 'state': state})
        observed = [item['state'].get('RealTimeProtectionEnabled') for item in report['defender_samples']
                    if isinstance(item['state'].get('RealTimeProtectionEnabled'), bool)]
        report['defender_changed'] = len(set(observed)) > 1
        return state

    def sample_defender(label):
        try:
            state = state_reader()
        except Exception as error:
            state = {'available': False, 'error_type': type(error).__name__}
        return record_defender(state, label)

    try:
        report['defender_start'] = sample_defender('start')
        required = 1_500_000_000 if mode == 'quick' else 3_000_000_000
        free = shutil.disk_usage(directory).free
        report['space_preflight'] = {'free_bytes': free, 'required_bytes': required, 'passed': free >= required}
        publish('Contrôle de l’espace disponible')
        if free < required:
            raise RuntimeError(f'Espace disponible insuffisant : {required} octets requis avant génération')
        _boundary(control)
        if focus != 'io' and os.name != 'nt' and worker_pair is None:
            raise RuntimeError('La comparaison complète utilise les API de Windows. Lancez le ZIP sur Windows ; '
                               'les microtests de copie seuls peuvent fonctionner sur cet autre système.')
        if focus != 'io':
            pair = pair or WorkerPair(baseline_source, final_source)
            report['implementation'] = pair.identity()
        owned = Path(tempfile.mkdtemp(prefix='lb-benchmark-', dir=directory))
        token = uuid.uuid4().hex
        if focus != 'io':
            for profile in restore_profiles:
                _boundary(control)
                root = owned / profile
                root.mkdir()
                (root / '.lifeboat-benchmark-owned.json').write_text(json.dumps(
                    {'purpose': 'synthetic-lifeboat-benchmark', 'token': token}), encoding='utf-8')
                if profile == restore_profiles[0]:
                    publish('Contrôle préalable : Codex et ChatGPT doivent être fermés')
                    run_worker(pair, 'final', root, token, 'preflight', 'preflight', profile, mode, control)
                publish('Préparation du jeu synthétique : ' + profile)
                fixture = run_worker(pair, 'baseline', root, token, 'build', 'build', profile, mode, control)
                report['fixtures'].append(fixture)
                publish()
                for repeat in range(repeats):
                    # Rotate three variants (or alternate two). No cold-cache claim.
                    offset = repeat % len(variants)
                    order = variants[offset:] + variants[:offset]
                    for variant in order:
                        _boundary(control)
                        label = f'{profile}, {variant}, passage {repeat + 1}/{repeats}'
                        publish('Restauration complète : ' + label)
                        before = sample_defender(label + ':before')
                        result = run_worker(pair, variant, root, token, 'restore',
                                            f'{variant}-{repeat}', profile, mode, control)
                        if result.get('protocol_version') != PROTOCOL_VERSION:
                            raise RuntimeError('Benchmark worker protocol does not match this launcher')
                        result.update(profile=profile, repeat=repeat, observation='first_pass' if repeat == 0 else 'subsequent_pass',
                                      cache_controlled=False, defender_before=before,
                                      defender_after=sample_defender(label + ':after'))
                        report['trials'].append(result)
                        publish()
                # Each profile owns its complete source, targets and safety roots.
                shutil.rmtree(root)
        if focus != 'restore':
            from microbench import run as run_io
            for profile in io_profiles:
                _boundary(control)
                seen = 0
                setup_seen = False

                def observed_io(value):
                    nonlocal seen, setup_seen
                    if not setup_seen and value.get('setup'):
                        for item in value['setup']:
                            if item['phase'] == 'archive_preparation':
                                report['archive_setup'].append({'profile': profile, 'seconds': item['seconds'],
                                                                'archive_bytes': value['archive_bytes']})
                        setup_seen = True
                    for row in value['results'][seen:]:
                        record_defender(row.get('defender_before', {}), profile + ':' + row['strategy'] + ':before')
                        record_defender(row.get('defender_after', {}), profile + ':' + row['strategy'] + ':after')
                        report['trials'].append(dict(kind='io', profile=profile, variant=row['strategy'],
                            repeat=row['repeat'], seconds=row['seconds'], valid=row['verified'],
                            observation='first_pass' if row['repeat'] == 0 else 'subsequent_pass',
                            cache_controlled=False, phases=row['phases'], defender_before=row.get('defender_before'),
                            defender_after=row.get('defender_after')))
                    seen = len(value['results'])
                    publish('Copies et archives : ' + profile)

                run_io(owned, count=300 if mode == 'quick' else 3000, size=4096,
                       repeats=repeats, profile=profile, observer=observed_io,
                       stop_requested=control.stop_after_trial.is_set,
                       cancel_requested=control.cancel.is_set)
                _boundary(control)
        report['status'] = 'complete'
        report['passed'] = len(report['trials']) == planned and all(t.get('valid') for t in report['trials'])
        if not report['passed']:
            report['status'] = 'failed'
    except StopAfterTrial:
        report['status'] = 'stopped'
    except (Cancelled, KeyboardInterrupt, InterruptedError):
        report['status'] = 'cancelled'
    except Exception as error:
        report['status'] = 'failed'
        report['errors'].append(_safe_error(error, owned, getattr(pair, 'sources', None)))
    finally:
        if owned is not None:
            try:
                shutil.rmtree(owned)
            except OSError as error:
                report['errors'].append('Nettoyage partiel du dossier synthétique : ' + type(error).__name__)
                report['temporary_cleanup_complete'] = False
            else:
                report['temporary_cleanup_complete'] = True
        report['defender_end'] = sample_defender('end')
        report['finished_at'] = utc_now()
        report.pop('current_activity', None)
        publish()
    return report, path


def main(argv=None):
    # PyInstaller's windowed launcher has no inherited console. The GUI uses its
    # own event queue; CLI automation reads the persisted JSON/TXT reports.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w', encoding='utf-8')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w', encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gui', action='store_true', help='Open the Windows benchmark interface')
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--directory', default='results')
    parser.add_argument('--mode', choices=['quick', 'thorough'], default='quick')
    parser.add_argument('--repeats', type=int)
    parser.add_argument('--focus', choices=['all', 'restore', 'io'], default='all')
    parser.add_argument('--baseline-source')
    parser.add_argument('--final-source')
    parser.add_argument('--include-archives', action='store_true', help='Also compare the final production archive format')
    args = parser.parse_args(argv)
    if args.final_source and not getattr(sys, 'frozen', False):
        # The coordinator imports only the shared Defender helper. Restores
        # always happen in their own independently selected worker processes.
        sys.path.insert(0, str(Path(args.final_source).resolve()))
    if args.gui or (not args.headless and not (argv if argv is not None else sys.argv[1:])):
        from benchmark_ui import launch
        return launch(args)
    def observe(report, path):
        print(f"[{len(report['trials'])}/{report['planned_trials']}] "
              f"{report.get('current_activity', report['status'])}", flush=True)
    report, path = run_suite(args.directory, args.mode, args.repeats, args.focus,
                            args.baseline_source, args.final_source, observer=observe,
                            include_archives=args.include_archives)
    print('JSON :', path, flush=True)
    print('Résumé :', path.with_suffix('.txt'), flush=True)
    print(DEFENDER_REMINDER, flush=True)
    return 0 if report['passed'] else 2 if report['status'] in ('stopped', 'cancelled') else 1


if __name__ == '__main__':
    raise SystemExit(main())
