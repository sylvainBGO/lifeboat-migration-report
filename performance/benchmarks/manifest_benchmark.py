"""Synthetic manifest benchmark: no user backup is accessed or modified."""
import argparse
import csv
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import sys
import tempfile
import time
from manifest_index import ManifestIndex


def baseline(package_root, project):
    # Selector semantics from Codex Lifeboat v3.4.11 (MIT, dkwolf1).
    prefix = str(project['backupRelativePath']).rstrip('/') + '/'
    entries = {}
    with (package_root / 'manifest' / 'sha256.csv').open('r', encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            relative_path = str(row['relative_path'])
            if relative_path.startswith(prefix):
                entries[relative_path[len(prefix):]] = (int(row['size']), str(row['sha256']).lower())
    return entries


def signature(entries):
    digest = hashlib.sha256()
    for key in sorted(entries):
        digest.update(json.dumps([key, entries[key]], ensure_ascii=True).encode())
        digest.update(b'\n')
    return digest.hexdigest()


def run(directory, rows=100000, projects=40, repeats=3):
    report = dict(schema=1, kind='manifest-index', platform=platform.platform(),
                  python=platform.python_version(), rows=rows, projects=projects,
                  repeats=repeats, results=[], completed=False,
                  limitations='Synthetic warm-cache test. Includes index construction. No file copy or content hashing. Timings exclude comparison signatures. SQLite cache target is not a process memory cap.')
    if shutil.disk_usage(directory).free < rows * 400 + 500_000_000:
        raise RuntimeError('Insufficient space for synthetic manifest and index plus reserve')
    with tempfile.TemporaryDirectory(prefix='lifeboat-manifest-bench-', dir=directory) as tmp:
        root = Path(tmp)
        (root / 'manifest').mkdir()
        start = time.perf_counter()
        with (root / 'manifest/sha256.csv').open('w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['relative_path', 'size', 'sha256'])
            for i in range(rows):
                writer.writerow([f'projects/p{i % projects}/f{i}', 4096, 'a' * 64])
        report['fixture_seconds'] = time.perf_counter() - start
        report['csv_bytes'] = (root / 'manifest/sha256.csv').stat().st_size
        expected = None
        for repeat in range(repeats):
            order = ['baseline', 'sqlite'] if repeat % 2 == 0 else ['sqlite', 'baseline']
            for strategy in order:
                print(f'{repeat+1}/{repeats}: {strategy} ({rows} rows, {projects} projects)', flush=True)
                start = time.perf_counter()
                index = ManifestIndex(root, directory=root) if strategy == 'sqlite' else None
                build = time.perf_counter() - start if index else 0
                elapsed = 0
                signatures = []
                disk = 0
                try:
                    for j in range(projects):
                        project = {'backupRelativePath': f'projects/p{j}'}
                        start = time.perf_counter()
                        selected = index.select(project) if index else baseline(root, project)
                        elapsed += time.perf_counter() - start
                        signatures.append(signature(selected))
                        del selected
                    disk = index.disk_bytes if index else 0
                finally:
                    if index:
                        index.close()
                if expected is None:
                    expected = signatures
                if signatures != expected:
                    raise AssertionError('Manifest selection differs')
                report['results'].append(dict(strategy=strategy, repeat=repeat,
                    build_seconds=build, select_seconds=elapsed, seconds=build+elapsed,
                    index_bytes=disk, csv_rows_read=rows if index else rows*projects,
                    identical_results=True))
                print(f'  {build+elapsed:.3f} seconds', flush=True)
    report['completed'] = True
    return report


def run_suite(directory, checkpoint, scenarios=((100000, 40, 3), (1000000, 40, 1))):
    report = dict(schema=1, kind='manifest-suite', completed=False, scenarios=[])
    checkpoint(report)
    try:
        for rows, projects, repeats in scenarios:
            report['current_scenario'] = dict(rows=rows, projects=projects, repeats=repeats)
            checkpoint(report)
            report['scenarios'].append(run(directory, rows, projects, repeats))
            checkpoint(report)
    except (Exception, KeyboardInterrupt) as error:
        report['error_type'] = type(error).__name__
        checkpoint(report)
        raise
    report.pop('current_scenario', None)
    report['completed'] = True
    checkpoint(report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', action='store_true', help='Run both manifest scenarios in one report')
    parser.add_argument('--directory', default='results')
    parser.add_argument('--rows', type=int, default=100000)
    parser.add_argument('--projects', type=int, default=40)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if not (1 <= args.rows <= 5_151_949 and 1 <= args.projects <= 100 and 1 <= args.repeats <= 5):
        parser.error('rows 1..5151949, projects 1..100, repeats 1..5')
    directory = Path(args.directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f'manifest-benchmark-{time.time_ns()}.json'
    def checkpoint(report):
        temporary = output.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, indent=2), encoding='utf-8')
        os.replace(temporary, output)
    try:
        report = run_suite(directory, checkpoint) if args.suite else run(directory, args.rows, args.projects, args.repeats)
    except (Exception, KeyboardInterrupt) as error:
        if not output.exists():
            checkpoint(dict(completed=False, error_type=type(error).__name__))
        print('Failed; report:', output, flush=True)
        return 1
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Report:', output, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
