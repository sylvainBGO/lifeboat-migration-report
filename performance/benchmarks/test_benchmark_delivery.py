"""Report/cancellation/ownership contracts, with no Defender changes.

Process orchestration uses a deliberately fake worker. Actual Windows restore
code and frozen binaries are exercised separately by the campaign workflow.
"""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from benchmark import RunControl, WorkerPair, run_suite
from benchmark_report import paired_comparisons, readable, _atomic_text
from microbench import run as run_microbench
from restore_worker import owned_root


class FakeWorkerPair:
    sources = None
    def __init__(self, directory, slow=False):
        self.script = Path(directory) / 'fake_worker.py'
        self.script.write_text('''import argparse,json,pathlib,time
p=argparse.ArgumentParser()
for key in ('root','token','action','trial','profile','mode','variant'):p.add_argument('--'+key)
a=p.parse_args()
root=pathlib.Path(a.root)
(root/'results').mkdir(exist_ok=True)
if a.action in ('build','preflight'):
 r={'profile':a.profile,'synthetic':True}
else:
 SLOW
 r={'kind':'restore','variant':a.variant,'seconds':1 if a.variant=='baseline' else 2,
    'valid':True,'durable_checkpoints':a.variant!='baseline','final_verification':True}
(root/'results'/(a.trial+'.json')).write_text(json.dumps(r))
'''.replace('SLOW', 'time.sleep(5)' if slow else 'pass'), encoding='utf-8')

    def command(self, variant):
        return [sys.executable, str(self.script)]

    def identity(self):
        return {'type': 'test-double-not-performance-evidence'}


class BenchmarkDeliveryTests(unittest.TestCase):
    def state(self):
        return {'available': True, 'RealTimeProtectionEnabled': True, 'IsTamperProtected': True}

    def test_stop_after_trial_preserves_unpaired_result_and_user_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sentinel = root / 'keep.txt'
            sentinel.write_text('user content', encoding='utf-8')
            pair = FakeWorkerPair(root)
            control = RunControl()
            def observe(value, path):
                if value['trials']:
                    control.stop_after_trial.set()
            report, path = run_suite(root, focus='restore', worker_pair=pair,
                control=control, observer=observe, state_reader=self.state)
            self.assertEqual(report['status'], 'stopped')
            self.assertFalse(report['passed'])
            self.assertEqual(len(report['trials']), 1)
            self.assertEqual(report['comparisons'], {})
            self.assertEqual(sentinel.read_text(), 'user content')
            self.assertEqual(json.loads(path.read_text())['status'], 'stopped')
            self.assertIn('Aucune paire complète', path.with_suffix('.txt').read_text())
            self.assertFalse(list(root.glob('lb-benchmark-*')))

    def test_cancel_running_synthetic_worker_saves_both_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            control = RunControl()
            timer = None
            def observe(value, path):
                nonlocal timer
                if value.get('current_activity', '').startswith('Restauration complète') and timer is None:
                    timer = threading.Timer(.15, control.cancel.set)
                    timer.start()
            started = time.monotonic()
            report, path = run_suite(root, focus='restore', worker_pair=FakeWorkerPair(root, slow=True),
                control=control, observer=observe, state_reader=self.state)
            if timer:
                timer.join()
            self.assertLess(time.monotonic() - started, 4)
            self.assertEqual(report['status'], 'cancelled')
            self.assertFalse(report['passed'])
            self.assertTrue(path.is_file())
            self.assertIn('INTERROMPU', path.with_suffix('.txt').read_text())
            self.assertFalse(list(root.glob('lb-benchmark-*')))

    def test_completed_orchestration_reports_a_regression_honestly(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report, path = run_suite(root, focus='restore', worker_pair=FakeWorkerPair(root), state_reader=self.state)
            self.assertTrue(report['passed'])
            self.assertEqual(len(report['trials']), 4)
            self.assertEqual(report['comparisons']['small']['reduction_percent'], -100)
            self.assertIn('-100.0 %', path.with_suffix('.txt').read_text())

    def test_space_preflight_fails_before_any_fixture_and_remains_reportable(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('benchmark.shutil.disk_usage', return_value=SimpleNamespace(free=1)):
                report, path = run_suite(folder, focus='io', state_reader=self.state)
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['trials'], [])
            self.assertFalse(report['space_preflight']['passed'])
            self.assertTrue(path.with_suffix('.txt').is_file())
            self.assertIn('réactiver', path.with_suffix('.txt').read_text())

    def test_microbench_stops_at_trial_boundary_and_preserves_content_guarantee(self):
        with tempfile.TemporaryDirectory() as folder:
            stopped = threading.Event()
            observed = []
            def observe(value):
                observed.append(len(value['results']))
                stopped.set()
            with patch('microbench.defender_state', return_value=self.state()):
                report = run_microbench(folder, count=12, size=200, repeats=2,
                                        observer=observe, stop_requested=stopped.is_set)
            self.assertEqual(observed, [1])
            self.assertEqual(len(report['results']), 1)
            self.assertTrue(report['results'][0]['verified'])
            self.assertFalse(report['completed'])
            self.assertEqual(report['status'], 'stopped')
            self.assertFalse(list(Path(folder).iterdir()))

    def test_comparison_rejects_candidate_without_durable_checkpoints(self):
        common = dict(kind='restore', profile='small', repeat=0, valid=True, seconds=1)
        rows = [dict(common, variant='baseline'), dict(common, variant='final', durable_checkpoints=False)]
        self.assertEqual(paired_comparisons(rows), {})

    def test_known_defender_difference_never_produces_a_gain_even_with_missing_samples(self):
        common = dict(kind='restore', profile='small', repeat=0, valid=True, seconds=1, durable_checkpoints=True)
        enabled = {'RealTimeProtectionEnabled': True}
        disabled = {'RealTimeProtectionEnabled': False}
        for baseline_after, final_after in ((enabled, disabled), ({}, {}), (enabled, {})):
            rows = [dict(common, variant='baseline', defender_before=enabled, defender_after=baseline_after),
                    dict(common, variant='final', defender_before=disabled, defender_after=final_after)]
            self.assertEqual(paired_comparisons(rows), {})
        rows = [dict(common, variant='baseline', defender_before=enabled, defender_after=enabled),
                dict(common, variant='final', defender_before=enabled, defender_after={})]
        self.assertFalse(paired_comparisons(rows)['small']['defender_conditions_known'])

    def test_atomic_report_does_not_touch_an_existing_predictable_temporary(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'report.json'
            sentinel = path.with_name(path.name + '.tmp')
            sentinel.write_text('unrelated user data')
            _atomic_text(path, 'report')
            self.assertEqual(path.read_text(), 'report')
            self.assertEqual(sentinel.read_text(), 'unrelated user data')
            self.assertEqual(set(p.name for p in Path(folder).iterdir()), {'report.json', 'report.json.tmp'})

    def test_source_comparison_refuses_identical_directories_and_identical_code(self):
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / 'first'
            second = Path(folder) / 'second'
            for source in (first, second):
                (source / 'codex_transfer').mkdir(parents=True)
                (source / 'codex_transfer' / 'restore.py').write_text('same code')
            with self.assertRaisesRegex(ValueError, 'different source directories'):
                WorkerPair(first, first)
            with self.assertRaisesRegex(ValueError, 'contents are identical'):
                WorkerPair(first, second).identity()

    def test_frozen_worker_identity_is_checked_before_measurement(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'BENCHMARK-BUILD.json').write_text(json.dumps({'workers': {'baseline': {'sha256': 'wrong'}}}))
            (root / 'Lifeboat-Baseline-Worker.exe').write_bytes(b'changed executable')
            with self.assertRaisesRegex(RuntimeError, 'identity mismatch'):
                WorkerPair(executable_directory=root).identity()

    def test_worker_refuses_an_unmarked_directory_without_modifying_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'keep.txt').write_text('do not touch')
            with self.assertRaisesRegex(RuntimeError, 'ownership marker'):
                owned_root(root, 'token')
            self.assertEqual([p.name for p in root.iterdir()], ['keep.txt'])


class DefenderInteractionTests(unittest.TestCase):
    def test_only_confirmed_user_action_requests_disable_and_never_reenables(self):
        from benchmark_ui import DefenderAdapter
        class Backend:
            calls = 0
            enabled = True
            def status(self):
                return {'available': True, 'RealTimeProtectionEnabled': self.enabled}
            def request_disable(self):
                self.calls += 1
                self.enabled = False
                return {'available': True, 'RealTimeProtectionEnabled': False, 'requestExitCode': 0}
        backend = Backend()
        adapter = DefenderAdapter(backend)
        self.assertTrue(adapter.read()['RealTimeProtectionEnabled'])
        self.assertFalse(adapter.disable_after_confirmation(False)['requested'])
        self.assertEqual(backend.calls, 0)
        self.assertFalse(adapter.disable_after_confirmation(True)['RealTimeProtectionEnabled'])
        adapter.read()
        self.assertEqual(backend.calls, 1)
        self.assertFalse(backend.enabled)

    def test_uac_failure_or_policy_block_does_not_report_disabled(self):
        from benchmark_ui import DefenderAdapter
        class Backend:
            def status(self):
                return {'available': True, 'RealTimeProtectionEnabled': True, 'IsTamperProtected': True}
            def request_disable(self):
                raise OSError('request declined')
        result = DefenderAdapter(Backend()).disable_after_confirmation(True)
        self.assertTrue(result['RealTimeProtectionEnabled'])
        self.assertEqual(result['request_error'], 'OSError')


if __name__ == '__main__':
    unittest.main()
