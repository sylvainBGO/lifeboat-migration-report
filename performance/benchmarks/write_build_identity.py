"""Record exact benchmark worker/source identities after a Windows build."""
import argparse
import json
import os
from pathlib import Path

from benchmark import file_hash, source_hash, baseline_provenance
from benchmark_report import _atomic_text, utc_now


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline-source', required=True)
    parser.add_argument('--final-source', required=True)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--repository', required=True)
    args = parser.parse_args()
    directory = Path(args.directory)
    repository = Path(args.repository)
    patches = ['performance/optimizations/restore-first-pass.patch',
               'features/resume-copy-foundation.patch', 'features/completion.patch']
    hashes = {'baseline': source_hash(args.baseline_source), 'final': source_hash(args.final_source)}
    if hashes['baseline'] == hashes['final']:
        raise ValueError('Baseline and final sources must not be identical')
    identity = dict(schema=1, built_at=utc_now(), baseline_provenance=baseline_provenance(args.baseline_source),
                    report_commit=os.environ.get('GITHUB_SHA', 'local-build'),
                    workflow_run=os.environ.get('GITHUB_RUN_ID'),
                    source_sha256=hashes,
                    patches={name: file_hash(repository / name) for name in patches},
                    final_path='prepare_restore + create_document + resume_from_document',
                    workers={variant: {'sha256': file_hash(directory / filename)} for variant, filename in
                             [('baseline', 'Lifeboat-Baseline-Worker.exe'), ('final', 'Lifeboat-Final-Worker.exe')]})
    _atomic_text(directory / 'BENCHMARK-BUILD.json', json.dumps(identity, indent=2) + '\n')
    _atomic_text(directory / 'SHA256.txt', ''.join(f'{file_hash(path)}  {path.name}\n' for path in sorted(directory.glob('*.exe'))))


if __name__ == '__main__':
    main()
