"""One-run synthetic campaign. Never accepts a user backup or restore target."""
import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
import ctypes
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from unittest.mock import patch

UPSTREAM = '4fe9724ccb54422455544e56b54399fa2bc94bc3'


def save(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def resources():
    if os.name != 'nt':
        return {'available': False}
    from ctypes import wintypes as w
    class Memory(ctypes.Structure):
        _fields_ = [('cb', w.DWORD), ('PageFaultCount', w.DWORD)] + [(n, ctypes.c_size_t) for n in ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    class IO(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    handle = kernel.GetCurrentProcess()
    mem = Memory(); mem.cb = ctypes.sizeof(mem)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.POINTER(Memory), w.DWORD]
    kernel.GetProcessIoCounters.argtypes = [w.HANDLE, ctypes.POINTER(IO)]
    io = IO()
    if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(mem), mem.cb) or not kernel.GetProcessIoCounters(handle, ctypes.byref(io)):
        return {'available': False}
    return dict(available=True, peak_working_set_bytes=mem.PeakWorkingSetSize,
                io={n:getattr(io,n) for n,_ in IO._fields_},
                scope='Entire scenario process including fixture/setup. OS logical I/O counters, not physical disk bytes.')


class Trace:
    def __init__(self):
        self.phase = 'setup'
        self.metrics = defaultdict(Counter)
        self.hash_paths = Counter()
        self.copy_destinations = Counter()
        self.stack = ExitStack()

    def timed(self, module, name):
        original = getattr(module, name)
        def wrapper(*args, **kwargs):
            previous = self.phase
            label = module.__name__.split('.')[-1] + '.' + name
            self.phase = label
            start = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                self.metrics[label]['inclusive_seconds'] += time.perf_counter() - start
                self.metrics[label]['calls'] += 1
                self.phase = previous
        self.stack.enter_context(patch.object(module, name, wrapper))

    def track(self, module, name, kind, path_index):
        original = getattr(module, name)
        def wrapper(*args, **kwargs):
            source = Path(args[0])
            size = source.stat().st_size if source.is_file() else 0
            result = original(*args, **kwargs)
            self.metrics[self.phase][kind + '_calls'] += 1
            self.metrics[self.phase][kind + '_logical_bytes'] += size
            path = os.path.normcase(str(Path(args[path_index]).resolve()))
            (self.hash_paths if kind == 'hash' else self.copy_destinations)[path] += 1
            return result
        self.stack.enter_context(patch.object(module, name, wrapper))

    def __enter__(self):
        from codex_transfer import backup, restore
        validate = importlib.import_module('codex_transfer.validate')
        for name in ('build_backup',):
            self.timed(backup, name)
        for name in ('prepare_restore','restore_backup','_restore_projects','_verify_staged_project',
                     '_restore_portable_profile','_restore_sessions','_restore_attachments',
                     '_build_restored_database','verify_restored','_ensure_restore_space','_project_manifest_entries'):
            if hasattr(restore, name):
                self.timed(restore, name)
        self.track(backup, 'sha256_file', 'hash', 0)
        self.track(validate, 'sha256_file', 'hash', 0)
        self.track(shutil, 'copy2', 'copy', 1)
        self.track(restore, '_rewrite_copy', 'rewrite', 1)
        return self

    def __exit__(self, *args):
        self.stack.close()

    def summary(self):
        return dict(phases=dict(self.metrics),
                    repeated_hash_calls_same_path=sum(max(0,n-1) for n in self.hash_paths.values()),
                    repeated_writes_same_destination=sum(max(0,n-1) for n in self.copy_destinations.values()),
                    coverage='Instrumented backup/validate SHA functions, shutil.copy2 and rollout rewrites. Counts include backup and restore; renamed paths are distinct. No claim of exhaustive physical reads. Phase times are inclusive and must not be summed.')


def restore_case(root, profile, smoke):
    from codex_transfer import selftest, backup, restore
    from manifest_index import ManifestIndex
    from microbench import payload
    source = root / 'source'
    codex, project = selftest._write_source(source)
    extra = []
    count = 20 if smoke else (5000 if profile == 'small' else 200)
    size = 1024 if profile == 'small' else (4096 if smoke else 512*1024)
    roots = [project]
    if profile == 'small':
        for j in range(1, 4 if smoke else 40):
            other = source / 'Documents' / f'Project{j}'
            other.mkdir(parents=True)
            roots.append(other)
            extra.append({'path':str(other), 'required':True})
    if profile == 'large' and not smoke:
        count, size = 8, 16*1024*1024
    for i in range(count):
        dest = roots[i % len(roots)] / 'payload' / f'd{i//100}' / f'f{i}.bin'
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload(i,size,'mixed'))
    if profile == 'overlap':
        # Explicit parent/child projects plus a portable-profile destination overlap.
        nested = project / 'nested'; nested.mkdir()
        (nested/'nested.txt').write_text('nested fixture', encoding='utf-8')
        portable = codex / '.chatgpt-projects' / 'fixture' / 'work'
        portable.mkdir(parents=True)
        (portable/'data.bin').write_bytes(b'fixture' * 100)
        extra = [{'path':str(nested), 'required':True}, {'path':str(portable), 'required':True}]
    config = root/'config.json'
    save(config, dict(configVersion=1, includeAttachments=True, projects=extra,
         additionalPortablePaths=[], excludeDirectoryNames=[],
         projectRegistryPath=str(root/'state/registry.json'), lineageStatePath=str(root/'state/lineage.json'),
         deviceStatePath=str(root/'state/device.json')))
    args = argparse.Namespace(config=str(config), destination=str(root/'packages'),
        source_profile=str(source), source_codex_home=str(codex), allow_running_test=True)
    results = []
    with Trace() as backup_trace:
        started = time.perf_counter()
        package = backup.build_backup(args)
        backup_seconds = time.perf_counter()-started
    collision_check = None
    if profile == 'overlap':
        collision_target = root / 'collision-target'
        selftest._write_target(collision_target, 'COLLISION')
        before = selftest._hash_tree(collision_target)
        try:
            restore.prepare_restore(package, collision_target, allow_running_test=True)
        except restore.RestoreError as error:
            if 'collides or overlaps' not in str(error):
                raise
            collision_check = dict(rejected=True, target_unchanged=before == selftest._hash_tree(collision_target))
        else:
            raise AssertionError('Overlapping project targets were not rejected')
        if not collision_check['target_unchanged']:
            raise AssertionError('Rejected collision changed destination')
        # Keep a nested directory within its parent, but no second project owns it.
        # Retain the separately registered portable-profile project.
        values = json.loads(config.read_text(encoding='utf-8'))
        values['projects'] = extra[1:]
        save(config, values)
        args.destination = str(root / 'packages-safe')
        with Trace() as second_backup_trace:
            started = time.perf_counter()
            package = backup.build_backup(args)
            backup_seconds += time.perf_counter() - started
    for variant in ('baseline','indexed'):
        target = root / variant
        selftest._write_target(target,'TEST')
        start = time.perf_counter()
        with Trace() as trace, ExitStack() as stack:
            if variant == 'indexed':
                index = stack.enter_context(ManifestIndex(package, directory=root))
                # Experimental staging selection only. Final validation unchanged.
                stack.enter_context(patch.object(restore, '_project_manifest_entries', lambda package, item:index.select(item)))
            prepared = restore.prepare_restore(package, target, allow_running_test=True)
            restored = restore.restore_backup(package,target,Path(prepared['safetyRoot']))
        results.append(dict(variant=variant, seconds=time.perf_counter()-start,
            valid=bool(restored['verification']['valid']),
            operations=trace.summary(), verification=restored['verification']['checks']))
    return dict(passed=all(r['valid'] for r in results), profile=profile,
                backup_seconds=backup_seconds, results=results, backup_operations=backup_trace.summary(),
                collision_check=collision_check,
                secondary_backup_operations=second_backup_trace.summary() if profile == 'overlap' else None,
                fixture=dict(added_files=count, added_bytes=count*size, additional_project_roots=len(extra)),
                limitations='Same generated package; baseline runs first (cache bias). Indexed variant only replaces staging manifest selection. Official source/target fixtures include JSONL, ZST, attachment, SQLite and retained authentication.')


def parallel_case(root, smoke):
    from concurrent.futures import ThreadPoolExecutor
    from microbench import payload, digest, verify
    source = root/'source'; source.mkdir()
    manifest = {}
    for i in range(30 if smoke else 3000):
        name=f'f{i}.bin'; data=payload(i,4096,'mixed')
        (source/name).write_bytes(data); manifest[name]=hashlib.sha256(data).hexdigest()
    results=[]
    for workers in (1,2,4,8):
        target=root/f'w{workers}'; target.mkdir()
        start=time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda name:shutil.copy2(source/name,target/name),manifest))
        copy_seconds=time.perf_counter()-start
        start=time.perf_counter(); verify(target,manifest)
        results.append(dict(workers=workers,copy_seconds=copy_seconds,
            verify_seconds=time.perf_counter()-start,valid=True))
        shutil.rmtree(target)
    return dict(passed=True,results=results,limitations='Synthetic copy2 worker-count comparison, fixed order, warm cache. No production parallel restore implementation.')


def resume_case(root):
    # Test a checkpoint concept, not a claim that upstream supports resume.
    from microbench import digest
    source=root/'source'; source.mkdir(); target=root/'target'; target.mkdir()
    for i in range(12): (source/str(i)).write_bytes(bytes([i])*4096)
    journal=root/'checkpoint.json'; state={'done':[]}
    save(journal,state)
    copied=Counter()
    def attempt(free_bytes, stop_after=None):
        state=json.loads(journal.read_text(encoding='utf-8'))
        for item in sorted(source.iterdir()):
            if item.name in state['done']: continue
            if free_bytes < 500_000_000 + item.stat().st_size: return 'space_pause'
            temporary=target/(item.name+'.tmp')
            shutil.copy2(item,temporary)
            if digest(item)!=digest(temporary): raise ValueError('corruption')
            os.replace(temporary,target/item.name); copied[item.name]+=1
            state['done'].append(item.name); save(journal,state)
            if stop_after and len(state['done'])==stop_after: return 'interrupted'
        return 'complete'
    interrupted=attempt(1_000_000_000,4)
    paused=attempt(499_999_999)
    completed=attempt(1_000_000_000)
    checks=dict(interruption=interrupted=='interrupted', low_space=paused=='space_pause',
        resumed=completed=='complete', no_duplicate_copies=all(n==1 for n in copied.values()) and len(copied)==12,
        contents=all(digest(p)==digest(target/p.name) for p in source.iterdir()))
    return dict(passed=all(checks.values()),checks=checks,
        limitations='Isolated persistent checkpoint concept with injected interruption and simulated free-space values. Not Lifeboat production resume; no power-loss simulation.')


def worker(root, scenario, smoke):
    if scenario.startswith('restore-'): return restore_case(root,scenario[8:],smoke)
    if scenario=='parallel': return parallel_case(root,smoke)
    if scenario=='resume-concept': return resume_case(root)
    if scenario=='official-regression':
        from codex_transfer import selftest
        result=selftest.run_self_test(root/'official')
        return dict(passed=result['passed'],checks=result['checks'],git_available=bool(shutil.which('git')), 
                    limitations='Official suite on synthetic profiles. Packaged GUI check is skipped by upstream. Git-dependent checks require Git on PATH.')
    if scenario=='manifest':
        from manifest_benchmark import run_suite
        scenarios=((1000,4,1),(2000,4,1)) if smoke else ((100000,40,3),(1000000,40,1))
        result=run_suite(root,lambda r:None,scenarios)
        return dict(passed=result['completed'],data=result)
    if scenario.startswith('io-'):
        from microbench import run
        profile=scenario[3:]
        result=run(root,30 if smoke else 3000,4096,1 if smoke else 3,profile)
        return dict(passed=all(r['verified'] for r in result['results']),data=result)
    raise ValueError('Unknown scenario')


def sanitize(value, root):
    # No absolute fixture/report paths needed in exported measurements.
    if isinstance(value,dict): return {k:sanitize(v,root) for k,v in value.items()}
    if isinstance(value,list): return [sanitize(v,root) for v in value]
    if isinstance(value,str):
        return value.replace(str(root),'<fixture>').replace(str(root).replace('\\','/'),'<fixture>')
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',default='results')
    parser.add_argument('--smoke',action='store_true')
    parser.add_argument('--worker',choices=['restore-small','restore-large','restore-overlap','parallel','resume-concept','official-regression','manifest','io-mixed','io-incompressible','io-compressible'])
    parser.add_argument('--root')
    args=parser.parse_args()
    if args.worker:
        root=Path(args.root).resolve()
        # Parent creates marker. Reject accidental use against an existing backup/profile.
        if not (root/'.campaign-owned').is_file(): raise RuntimeError('Missing ownership marker')
        tempfile.tempdir=str(root)
        started=time.perf_counter()
        try:
            result=worker(root,args.worker,args.smoke)
        except BaseException as error:
            result=dict(passed=False,error_type=type(error).__name__,error=str(error),traceback=traceback.format_exc())
        result.update(seconds=time.perf_counter()-started,resources=resources())
        save(root/'result.json',sanitize(result,root))
        return 0 if result['passed'] else 1
    if os.name!='nt': raise RuntimeError('Complete campaign must run on Windows')
    output_root=Path(args.directory).resolve(); output_root.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(output_root).free < 3_000_000_000:
        raise RuntimeError('At least 3 GB free required for isolated campaign')
    output=output_root/f'campagne-lifeboat-{time.time_ns()}.json'
    from microbench import defender_state
    report=dict(schema=1,upstream_commit=UPSTREAM,completed=False,passed=False,
        smoke=args.smoke,defender_start=defender_state(),scenarios=[],
        limitations=['Synthetic data, not original 88 GiB backup. No two-hour guarantee.',
          'No change to Defender. OS cache not flushed. Full-scale disk allocation and peak memory require representative production validation.',
          'ZIP, parallel copy and resume concept are isolated prototypes; not production restore variants.'])
    save(output,report)
    scenarios=['restore-small','restore-large','restore-overlap','manifest','io-mixed','io-incompressible','io-compressible','parallel','resume-concept','official-regression']
    try:
        for number,scenario in enumerate(scenarios,1):
            print(f'[{number}/{len(scenarios)}] {scenario}',flush=True)
            with tempfile.TemporaryDirectory(prefix='lb-campaign-',dir=output_root) as tmp:
                root=Path(tmp); (root/'.campaign-owned').touch()
                command=([sys.executable] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).resolve())])
                command+=['--worker',scenario,'--root',str(root)]
                if args.smoke: command+=['--smoke']
                env=os.environ.copy()
                for name in ('LOCALAPPDATA','APPDATA','TEMP','TMP'):
                    folder=root/name;folder.mkdir();env[name]=str(folder)
                start=time.monotonic()
                with (root/'worker.log').open('w',encoding='utf-8') as log:
                    process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=env)
                    try:
                        while process.poll() is None:
                            if time.monotonic()-start>1800:
                                process.kill();process.wait();break
                            time.sleep(1)
                            if int(time.monotonic()-start)%30==0:
                                print(f'  {scenario}: {int(time.monotonic()-start)} s',flush=True)
                    finally:
                        if process.poll() is None: process.kill();process.wait()
                result_path=root/'result.json'
                result=json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else dict(passed=False,error_type='WorkerFailedOrTimedOut')
                result.update(scenario=scenario,exit_code=process.returncode)
                if process.returncode: result['passed']=False
                if not result['passed']:
                    result['log_tail']=sanitize((root/'worker.log').read_text(encoding='utf-8',errors='replace')[-12000:],root)
                report['scenarios'].append(result);save(output,report)
                print('  OK' if result['passed'] else '  ECHEC (la campagne continue)',flush=True)
        report['completed']=True
    except KeyboardInterrupt:
        report['interrupted']=True
    finally:
        report['defender_end']=defender_state()
        report['passed']=report['completed'] and all(r['passed'] for r in report['scenarios'])
        save(output,report)
    print('Rapport unique:',output,flush=True)
    print('Si vous avez desactive Defender, pensez a le reactiver.',flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':
    sys.exit(main())
