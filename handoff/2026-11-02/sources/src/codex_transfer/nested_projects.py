"""Restore byte-identical nested snapshots as one transactional tree.

No project names are special. Old packages remain immutable. Divergent snapshots
are deliberately rejected: timestamps are not evidence of which copy is right.
"""
from __future__ import annotations

import csv
import json
from pathlib import PureWindowsPath
from .fs_paths import Path
from typing import Any


def source_relative(parent: str, child: str) -> str | None:
    """Compare source paths using Windows semantics, including on Linux tests."""
    try:
        relative = PureWindowsPath(child).relative_to(PureWindowsPath(parent))
    except ValueError:
        return None
    return relative.as_posix() if relative.parts else None


def analyze(items: list[dict[str, Any]], package_root: Path | None) -> dict[str, Any]:
    parents: dict[str, str] = {}
    errors: list[dict[str, str]] = []
    by_id = {str(item['id']): item for item in items}
    offsets: dict[str, str] = {}
    for child in items:
        candidates = []
        target = PureWindowsPath(str(child['targetPath']))
        for parent in items:
            if parent is child:
                continue
            parent_target = PureWindowsPath(str(parent['targetPath']))
            if target == parent_target:
                errors.append({'id': child['id'], 'error': f"target collides with project {parent['id']} (equal destination: {target})"})
                continue
            try:
                relative = target.relative_to(parent_target).as_posix()
            except ValueError:
                continue
            original_relative = source_relative(str(parent['sourcePath']), str(child['sourcePath']))
            if original_relative is None or original_relative.casefold() != relative.casefold():
                errors.append({'id': child['id'], 'error': f"Unrelated source projects overlap at destination: {parent_target} / {target}"})
                continue
            candidates.append((len(parent_target.parts), str(parent['id']), relative))
        if candidates:
            _, parent_id, relative = min(candidates)
            parents[str(child['id'])] = parent_id
            offsets[str(child['id'])] = relative
    if not parents or errors:
        return {'parents': parents, 'offsets': offsets, 'issues': errors}
    if package_root is None:
        errors.append({'id': '', 'error': 'Nested project snapshots require package manifest verification.'})
        return {'parents': parents, 'offsets': offsets, 'issues': errors}
    try:
        projects = json.loads((package_root / 'manifest/projects.json').read_text(encoding='utf-8-sig'))
        project_by_id = {str(p['id']): p for p in projects}
        involved = set(parents) | set(parents.values())
        prefixes = {str(project_by_id[k]['backupRelativePath']).rstrip('/') + '/': k for k in involved}
        rows: dict[str, dict[str, tuple[int, str]]] = {k: {} for k in involved}
        # One CSV pass, only keeping hashes belonging to the nested group.
        with (package_root / 'manifest/sha256.csv').open(encoding='utf-8-sig', newline='') as handle:
            for row in csv.DictReader(handle):
                name = row['relative_path']
                for prefix, key in prefixes.items():
                    if name.startswith(prefix):
                        relative = name[len(prefix):]
                        if relative in rows[key]:
                            raise ValueError('Duplicate project hash row: ' + name)
                        rows[key][relative] = (int(row['size']), row['sha256'].lower())
                        break
        for key, entries in rows.items():
            project = project_by_id[key]
            if len(entries) != int(project['fileCount']) or sum(v[0] for v in entries.values()) != int(project['totalBytes']):
                raise ValueError('Incomplete hash inventory for project ' + key)
        for child_id, parent_id in parents.items():
            prefix = offsets[child_id] + '/'
            parent_rows = {k[len(prefix):]: v for k, v in rows[parent_id].items() if k.startswith(prefix)}
            child_rows = rows[child_id]
            different = sorted(k for k in parent_rows.keys() | child_rows.keys() if parent_rows.get(k) != child_rows.get(k))
            if different:
                errors.append({'id': child_id, 'error': (
                    f"Nested snapshots differ: {by_id[parent_id]['sourcePath']} / {by_id[child_id]['sourcePath']}; "
                    f"{len(different)} differing or missing files (examples: {', '.join(different[:3])}). "
                    'Both copies remain in the backup; no version was selected or overwritten.'
                )})
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append({'id': '', 'error': 'Cannot verify nested project snapshots: ' + str(exc)})
    return {'parents': parents, 'offsets': offsets, 'issues': errors}


def decision_errors(plan: dict[str, Any]) -> list[str]:
    """A parent replacement must not override a reviewed child retention."""
    parents = (plan.get('locationPlan') or {}).get('nestedProjects', {}).get('parents', {})
    items = {str(i.get('key')): i for i in plan.get('items', []) if i.get('kind') == 'project'}
    errors = []
    for child_id, parent_id in parents.items():
        parent = items.get('project/' + parent_id, {})
        child = items.get('project/' + child_id, {})
        pa, ca = parent.get('proposedAction'), child.get('proposedAction')
        if pa in {'none', 'retain'} and ca in {'none', 'retain'}:
            continue
        if pa in {'create', 'replace'} and ca in {'create', 'replace', 'none'}:
            continue
        errors.append(f"Nested projects require compatible decisions: {parent.get('target')} ({pa}) / {child.get('target')} ({ca}). Keep both targets or restore both sources; per-child archives are not supported.")
    # Protect registered destination-only roots from replacement of an ancestor.
    for parent_id in set(parents.values()):
        parent = items.get('project/' + parent_id, {})
        if parent.get('proposedAction') not in {'create', 'replace'}:
            continue
        for item in items.values():
            if item.get('source') is None and item.get('target') and parent.get('target'):
                a, b = str(parent['target']), str(item['target'])
                if a.casefold() == b.casefold() or source_relative(a, b) or source_relative(b, a):
                    errors.append('Destination-only project overlaps nested group: ' + b)
    return errors
