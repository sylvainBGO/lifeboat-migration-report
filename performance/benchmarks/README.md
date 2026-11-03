# Lifeboat performance investigation — prototype 0.1

Baseline inspected: upstream v3.4.11, commit 4fe9724. Existing incident-specific v3.4.7 sources remain unchanged.

## First concrete findings

- `restore._project_manifest_entries` reads the SHA-256 CSV to select entries for each project. Investigate indexing once rather than parsing the whole CSV for each project.
- `_restore_projects` stages files, reads staged files to verify, and activates via a same-volume rename. Activation already avoids a second full copy: do not claim this is a new optimization.
- `verify_restored` reads a manifest and hashes project destinations again. Earlier evidence is only reusable if no later operation modifies those destinations.
- `_restore_portable_profile` removes/rebuilds supported destinations; potential overlap with project payloads requires a fixture demonstrating actual overlap before changing behavior.
- v3.4.11 already resets paginated history projection, because changing rollout bytes makes stored offsets stale. Preserve this correction.

## Prototype scope

`microbench.py` compares three synthetic I/O strategies. It is NOT the complete Lifeboat code path or a predictor of restore duration. Fixture generation and ZIP preparation are timed separately. All strategies verify the final file set and SHA-256 contents. Fused copy also validates source bytes while copying. ZIP uses CRC during extraction and final SHA-256 checking; this is not yet a production archive format.

Run Windows executable from a terminal:

```
Lifeboat-Microbench.exe --directory C:\LifeboatBench --files 3000 --bytes 4096 --repeats 3
```

Run from source with Python 3.11+:

```
python microbench.py --directory ./results --files 3000 --bytes 4096 --repeats 3
```

The only directory automatically removed is the unique temporary directory created by the benchmark. The JSON report remains in the chosen folder. Do not choose a synced/network folder unless intentionally testing it. No profile, backup, or private files are inspected. Ctrl+C interrupts the console prototype and cleans up its temporary data; interrupted runs do not yet preserve partial results.

Results include elapsed and process CPU times per phase, archive size, verification results, scenario size and platform. No physical disk I/O, peak RAM or NTFS allocation metrics are claimed. The fixture is deliberately compressible; incompressible and mixed realistic corpora are still needed. OS caches are not flushed; trials rotate order but are not cold-cache measurements. ZIP metadata preservation differs from copy2; no production equivalence claim.

## Next development gates

1. Add production-code adapters and per-operation counters; manifest lookup and nested-tree fixtures first.
2. Add mixed/incompressible fixtures, JSONL/ZST transformations and bounded concurrency trials.
3. Build Windows UI, cancellation with partial reports, resource metrics and free-space monitoring during tests.
4. Defender: explicit disable button with UAC; check startup then hourly; a single nonblocking reactivation prompt while workers continue; no automatic re-enable; end/error/cancel reminder. This prototype DOES NOT modify Defender.
5. Windows measurements before selecting production optimizations; maintain final correctness checks and test corruption.
6. Only after performance choices: generalized resume, pause and production progress UI.

## Validation

Automated tests cover destination corruption, changed source rejection, strategy completion and preserving an existing user file during cleanup. A Linux smoke run used 3,000 files of 4 KiB, three repetitions. It does not establish Windows performance or the two-hour goal.
