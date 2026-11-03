"""Run upstream manifest selector in isolation; avoids Windows-only module imports."""
import ast
import csv
import json
from pathlib import Path
import tempfile
import time
from typing import Any
import argparse

def run(source, rows=100000, projects=40):
    tree = ast.parse(Path(source).read_text(encoding='utf-8'))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_project_manifest_entries')
    namespace = {'Path': Path, 'Any': Any, 'csv': csv}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), 'exec'), namespace)
    selector = namespace[fn.name]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root/'manifest').mkdir()
        manifest = root/'manifest/sha256.csv'
        with manifest.open('w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['relative_path', 'size', 'sha256'])
            for i in range(rows):
                writer.writerow([f'projects/p{i%projects}/f{i}',4096,'a'*64])
        start = time.perf_counter()
        old = [selector(root, {'backupRelativePath': f'projects/p{j}'}) for j in range(projects)]
        old_seconds = time.perf_counter()-start
        start = time.perf_counter()
        indexed = [{} for _ in range(projects)]
        with manifest.open(newline='') as f:
            for row in csv.DictReader(f):
                _, project, name = row['relative_path'].split('/',2)
                indexed[int(project[1:])][name] = (int(row['size']), row['sha256'].lower())
        new_seconds = time.perf_counter()-start
        assert old == indexed
        return dict(rows=rows, projects=projects, upstream_seconds=old_seconds,
                    indexed_seconds=new_seconds, upstream_rows_parsed=rows*projects,
                    indexed_rows_parsed=rows, identical_results=True,
                    limitations='Isolated exact upstream function; synthetic flat prefixes; warm cache; not complete restore; memory budget and general path mapping still required')

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source')
    args=p.parse_args()
    print(json.dumps(run(args.source),indent=2))
