# Restore operation audit — v3.4.11

Scope: source inspection, not a trace of the user's interrupted 88.48 GiB restore.

## Confirmed repeated work

1. `restore.py:_project_manifest_entries` parses the entire SHA CSV once per staged project. Replace with a per-run index; prototype in benchmarks/manifest_index.py. It preserves selected path/size/hash mappings. Index build, disk allocation, cleanup, and memory must be counted.
2. `_verify_staged_project` enumerates and hashes the staged project. `_restore_projects` activates it by same-volume rename. `verify_restored` later enumerates the destination and hashes project files again.
3. `verify_restored` loads all manifest hashes into a Python dictionary, then loops over the complete dictionary for every project. The same per-run index could remove those repeated full-map scans and the global dictionary. This improves selection only, not hash I/O.

## Work that cannot simply be removed

- Final verification happens after portable-profile restoration, session rewrites, attachment copying and global-state installation. Some destinations may overlap. Reusing staging hashes requires an exact destination/write ownership analysis and invalidation, not a blanket flag.
- A same-volume rename is already implemented; this is not a new optimization.
- `backup.py:copy_portable_profile` excludes sessions, archived_sessions and primary live database state. Do not claim sessions are systematically copied twice through that path.
- Portable profile includes other trees, potentially `.chatgpt-projects`; determine actual destination overlap from mappings before suppressing any copy. No overlap volume has yet been measured for the original backup.
- `_rewrite_copy` processes text line by line and replaces via a temporary file. Rewrites change bytes, so original source hashes cannot serve as final destination hashes.
- Preserve paginated history projection invalidation when rollout bytes change.

## Next implementation order

1. Measure manifest index on Windows with 100k and 1m synthetic rows; include construction and temporary disk use.
2. Integrate a shared per-restore index into staging and final selection without removing file verification.
3. Add a read-only destination ownership plan identifying exact/same/ancestor paths under Windows semantics. Explicitly handle case, junctions/reparse points and mutable trees.
4. Count reads, copied bytes, hashes and repeated destination writes with a representative integration fixture; only then choose which verified results can safely be reused.

No production restore behavior is changed in this branch yet. Synthetic tests do not establish a two-hour restore target or real backup completeness.

## Confirmed space-check frequency (2026-11-03)

The `_copy_all` callback increments `files_since_check`, checks when it equals 1,
and resets it to zero after each check. Therefore the next file increments it to
1 again. An isolated execution of the exact AST-extracted upstream function with
100 synthetic `before_copy` callbacks produced 100 `_ensure_restore_space` calls.
The nominal 1024-file / 256 MiB thresholds do not reduce this frequency. Campaign
instrumentation records call count and inclusive duration; no space checks have
been removed. Any correction must preserve an appropriate reserve for the bytes
written between checks, including allocation overhead and concurrent consumers.
