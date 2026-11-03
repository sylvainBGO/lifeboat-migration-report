> Superseded by the [completed current-format performance pass and feature backlog](performance-pass-and-next-features.md). The patch now includes the complete pass, with final Windows validation and raw timing results.

# Restore optimization candidate — 2026-11-03

Based on dkwolf1/Codex-Lifeboat v3.4.11, commit 4fe9724ccb54422455544e56b54399fa2bc94bc3. Upstream MIT license applies to derived source. This is an experimental source patch, not a released recovery executable.

## Changes
- Build one disposable SQLite manifest index per restore, reuse it during staged project verification and final project verification, then clean it up.
- Standalone verification owns and cleans its own index. Final verification streams project hashes instead of loading the entire manifest into a Python dictionary and filtering it once per project.
- Preserve staged and final content verification, destination decision handling, transactional activation, and upstream rollback.
- Replace the file-counter reset bug with a conservative copy budget: debit each pending file's bytes plus filesystem allocation overhead from measured free space above the existing upstream reserve.
- Recheck before exhausting that budget, when the target drive anchor changes, after one second, after 1024 files, or when the pending file brings the batch to 256 MiB.
- Preserve existing low-space errors. This does not implement pause/resume or change the upstream reserve to the separately requested 500 MB value.

## Verification
18 local component tests pass, including the 7 new tests. Python source compilation and git whitespace checks pass.
The deterministic small-file test performs 5 probes for 5003 callbacks at fixed time, rather than 5003. Real copies can trigger additional time/budget probes.
Windows validation passed: 7 new component tests and all 97 upstream source regression flags, including GUI, tampering rejection, runtime reserve enforcement and rollback after journal ENOSPC. Initial workflow attempt failed before tests because checkout line endings differed; the workflow now normalizes the patch and target source before applying it.
https://github.com/sylvainBGO/lifeboat-migration-report/actions/runs/41686676753

## Limits and next work
The budget is not a filesystem reservation. External consumers can consume space between samples, and filesystem writes still require error handling. Existing rollback remains active.
The index is disposable and uses temporary disk space; its SQLite cache target is 8 MiB, but staging still materializes one project's inventory in memory. This is not a bound on whole-process RAM.
No elapsed-time claim for the original 88 GiB backup follows from component tests.
Do not rerun the old baseline-versus-index adapter on this modified source and interpret it as a valid comparison: production now already uses the shared index. Future performance comparison needs separate pinned baseline and candidate processes.
Next: measure the candidate as a whole; then integrate bounded native-copy concurrency and analyze write ownership before reusing verification results. No blanket removal of final hashes.
