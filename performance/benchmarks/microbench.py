"""Synthetic I/O strategy benchmark. Not a full Lifeboat restore benchmark."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import random
import sys
import shutil
import tempfile
import time
import zipfile

BLOCK = 1024 * 1024


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(BLOCK), b''):
            h.update(block)
    return h.hexdigest()


def verify(root, manifest):
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual != set(manifest):
        raise ValueError('File set mismatch')
    slowest = []
    read_start = time.perf_counter()
    for name, expected in manifest.items():
        start = time.perf_counter()
        if digest(root / name) != expected:
            raise ValueError('Content mismatch: ' + name)
        slowest.append(time.perf_counter() - start)
    return dict(hash_read_seconds=time.perf_counter()-read_start,
                slowest_file_seconds=sorted(slowest, reverse=True)[:10])


def fused_copy(src, dst, manifest, metadata=True):
    for name, expected in manifest.items():
        target = dst / name
        target.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        with (src / name).open('rb') as reader, target.open('xb') as writer:
            for block in iter(lambda: reader.read(BLOCK), b''):
                h.update(block)
                writer.write(block)
        if h.hexdigest() != expected:
            raise ValueError('Source changed: ' + name)
        if metadata:
            shutil.copystat(src / name, target)


def phase(rows, name, callback):
    start, cpu = time.perf_counter(), time.process_time()
    details = callback()
    row = dict(phase=name, seconds=time.perf_counter()-start,
               cpu_seconds=time.process_time()-cpu)
    if isinstance(details, dict):
        row['details'] = details
    rows.append(row)
    print(f"  {name}: {row['seconds']:.3f} s", flush=True)


def defender_state():
    if os.name != 'nt':
        return {'status': 'not_windows'}
    executable = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        result = subprocess.run([str(executable), '-NoProfile', '-NonInteractive', '-Command',
            'Get-MpComputerStatus -ErrorAction Stop | Select-Object RealTimeProtectionEnabled,IsTamperProtected,AntivirusEnabled | ConvertTo-Json -Compress'],
            capture_output=True, text=True, timeout=20, creationflags=0x08000000)
        if result.returncode:
            return {'status': 'unavailable', 'exit_code': result.returncode}
        return {'status': 'ok', **json.loads(result.stdout)}
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {'status': 'unavailable'}


def payload(index, size, profile):
    seed = hashlib.sha256(str(index).encode()).digest()
    if profile == 'compressible' or (profile == 'mixed' and index % 2 == 0):
        return (seed * ((size+31)//32))[:size]
    return hashlib.shake_256(seed).digest(size)


def run(base, count=3000, size=4096, repeats=2, profile="mixed", observer=None):
    base = Path(base).resolve()
    base.mkdir(parents=True, exist_ok=True)
    # Only this newly generated directory is ever removed.
    if shutil.disk_usage(base).free < count * size * 4 + 500_000_000:
        raise ValueError('Insufficient free space for fixture, outputs and 500 MB reserve')
    root = Path(tempfile.mkdtemp(prefix='lifeboat-bench-', dir=base))
    report = dict(schema=2, version="0.2", profile=profile, platform=platform.platform(), python=platform.python_version(),
                  file_count=count, file_bytes=size, repeats=repeats, results=[],
                  limitations=['Synthetic strategies, not full restore timings',
                               'Warm OS cache; no cache eviction or physical I/O measurement',
                               'SHA-256 destination readback is not a physical durability guarantee',
                               'ZIP preparation is measured separately; metadata fidelity not equivalent',
                               'No Defender settings changed'])
    report['defender_start'] = defender_state()
    try:
        src = root / 'source'
        manifest = {}
        setup = []
        def generate():
            for i in range(count):
                name = f'{i // 100:05d}/{i:08d}.dat'
                path = src / name
                path.parent.mkdir(parents=True, exist_ok=True)
                # Mixed repeatable content, intentionally only one compression profile.
                data = payload(i, size, profile)
                path.write_bytes(data)
                manifest[name] = hashlib.sha256(data).hexdigest()
        phase(setup, 'fixture_generation', generate)
        archive = root / 'payload.zip'
        def pack():
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as z:
                for name in manifest:
                    z.write(src/name, name)
        phase(setup, 'archive_preparation', pack)
        report.update(setup=setup, archive_bytes=archive.stat().st_size)
        strategies = ['separate', 'copyfile', 'fused', 'fused_no_metadata', 'copytree_no_metadata', 'zip']
        for repeat in range(repeats):
            # Rotate order to reduce fixed-order bias, without pretending caches are cold.
            order = list(strategies)
            random.Random(20261103 + repeat).shuffle(order)
            for strategy in order:
                rows = []
                dst = root / f'destination-{repeat}-{strategy}'
                state = report['defender_start']
                print(f'{repeat+1}/{repeats}: {strategy}', flush=True)
                if strategy == 'separate':
                    phase(rows, 'source_verify', lambda: verify(src, manifest))
                    phase(rows, 'copy', lambda: shutil.copytree(src, dst))
                elif strategy == 'copytree_no_metadata':
                    phase(rows, 'source_verify', lambda: verify(src, manifest))
                    phase(rows, 'copy', lambda: shutil.copytree(src, dst, copy_function=shutil.copyfile))
                elif strategy == 'copyfile':
                    phase(rows, 'source_verify', lambda: verify(src, manifest))
                    def listed_copy():
                        for name in manifest:
                            target = dst/name
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(src/name, target)
                    phase(rows, 'listed_copy2', listed_copy)
                elif strategy in ('fused', 'fused_no_metadata'):
                    phase(rows, 'copy_and_source_hash', lambda: fused_copy(src, dst, manifest, strategy == 'fused'))
                else:
                    # Archive is generated by this program; no external archive accepted.
                    def extract():
                        with zipfile.ZipFile(archive) as z:
                            z.extractall(dst)
                    phase(rows, 'extract_with_crc', extract)
                phase(rows, 'destination_verify', lambda: verify(dst, manifest))
                report['results'].append(dict(strategy=strategy, repeat=repeat, defender_before=state,
                    defender_sample='run_start',
                    phases=rows, seconds=sum(x['seconds'] for x in rows), verified=True))
                if observer:
                    observer(report)
                shutil.rmtree(dst)
        report['defender_end'] = defender_state()
        return report
    finally:
        shutil.rmtree(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', default='.')
    parser.add_argument('--files', type=int, default=3000)
    parser.add_argument('--bytes', type=int, default=4096)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--profile', choices=['compressible','incompressible','mixed'], default='mixed')
    args = parser.parse_args()
    if not (1 <= args.files <= 100000 and 1 <= args.bytes <= 1048576 and 1 <= args.repeats <= 10):
        parser.error('Allowed: files 1..100000, bytes 1..1048576, repeats 1..10')
    if args.files * args.bytes > 2 * 1024**3:
        parser.error('This microbenchmark is capped at 2 GiB of fixture data')
    base = Path(args.directory).resolve()
    base.mkdir(parents=True, exist_ok=True)
    output = base / ('benchmark-v2-' + str(time.time_ns()) + '.json')
    def checkpoint(report):
        temp = output.with_suffix('.tmp')
        temp.write_text(json.dumps(report, indent=2), encoding='utf-8')
        os.replace(temp, output)
    try:
        result = run(base, args.files, args.bytes, args.repeats, args.profile,
                     lambda report: checkpoint(dict(report, completed=False)))
        result['completed'] = True
        checkpoint(result)
    except (KeyboardInterrupt, Exception) as error:
        if output.exists():
            partial = json.loads(output.read_text(encoding='utf-8'))
        else:
            partial = {'schema': 2, 'version': '0.2', 'results': []}
        partial.update(completed=False, error_type=type(error).__name__)
        checkpoint(partial)
        print('Interrupted or failed. Partial report:', output, flush=True)
        return 1
    print('Report:', output, flush=True)
    return 0

if __name__ == '__main__':
    sys.exit(main())
