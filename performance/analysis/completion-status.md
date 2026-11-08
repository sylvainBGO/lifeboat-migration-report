# Community completion — implementation and acceptance

This change completes the remaining recovery and benchmark work on top of
Community Recovery 14. The reproducible source is upstream v3.4.11, commit
`4fe9724ccb54422455544e56b54399fa2bc94bc3`, followed by these patches in order:

1. `performance/optimizations/restore-first-pass.patch`
2. `features/resume-copy-foundation.patch`
3. `features/completion.patch`

The first two patches are unchanged. Historical incident evidence and release 14
remain available. The new source archive contains the integrated application and
the separate benchmark sources.

## Delivered behavior

| Area | Implementation |
| --- | --- |
| Startup and resume | Discover bounded recovery-plan metadata for the current profile; load the newest valid unfinished plan without starting restoration. Offline source media is reported. Manual loading remains available. |
| Durable recovery | Existing 500,000,000-byte reserve, copy checkpoints, transaction journal, final verification and rollback/retention lifecycle remain in use. Archived projects use the same recovery operation. |
| Defender | Explicit confirmation followed by Windows UAC, actual-state verification, manual instructions if blocked, and a manual-reactivation reminder on success, cancellation, error, pause and exit. There is no automatic reactivation or silent repeated disabling. |
| Project archives | Optional production `archive-blocks-v1` backup storage, format 2.5. Direct block creation and extraction into the existing staging tree; logical file SHA-256 plus physical block hashes; exact supported timestamps/modes and empty directories; resumable extraction. Ordinary file backups remain the default. |
| Local conversation pre-read | Optional bounded read of up to 50 recent local rollout files. It warms temporary OS file cache only. It does not load a persistent Codex application cache, call an agent or open a conversation through the app. |
| Benchmark delivery | Windows launcher with quick/thorough modes, versioned synthetic scenarios, space check, stop after the current trial, isolated original/final workers and JSON plus readable text reports. |
| Actual final performance | Compare the original upstream restore with the final durable recovery path and its archive variant. Measure backup creation, restoration and combined elapsed time separately. Integrity checks stay inside restoration timing. |

Archive backups require this new Community reader; the original upstream reader
cannot restore format 2.5. The optional archive mode rejects unsupported links,
alternate data streams, EFS and exposed extended attributes instead of silently
discarding them. Windows ACLs, ownership, creation time and access time are not
part of its metadata contract. See `docs/archive-blocks.md` in the source ZIP.

Local pre-reading reads only bounded metadata and file bytes, uses a disposable
SQLite snapshot when available, and leaves original databases and conversations
unchanged. Reports contain aggregate counts rather than conversation titles,
identifiers or content. A report cannot be written over a file in the selected
Codex home. See `docs/conversation-warmup.md` in the source ZIP.

## Acceptance gate

The [Windows workflow](https://github.com/sylvainBGO/lifeboat-migration-report/actions/workflows/restore-features.yml)
is the consolidated publication gate. It runs:

- Component and failure-injection tests, with Defender mutations replaced by mocks.
- The upstream source regression, including normal restoration, GUI and rollback.
- Packaged application regression and compatibility scenarios.
- Packaged pause/reopen recovery for ordinary files and archived projects.
- Packaged local pre-read against three synthetic files.
- Packaged application open/close, plus synthetic screenshots.
- Benchmark contracts, synthetic UI verification and a bounded quick campaign
  through the packaged original and final workers, including the production
  archive format.

Branch builds publish review artifacts only. The main-branch job publishes a
prerelease only after every required check has passed. The release includes the
application ZIP, benchmark ZIP, source ZIP, build provenance and SHA-256 checksums.
The benchmark workflows remain available for explicitly requested supplementary
campaigns rather than automatically repeating this acceptance gate.

At the preparation of this commit, local Linux discovery ran 112 component tests:
76 passed and 36 were skipped because they require Windows. This is not evidence
that the Windows executable has passed. The final Windows run, published release
and measured results will be recorded below after completion.

## Performance interpretation

Only complete, valid trials enter comparisons. Known different or changing
Defender conditions must not produce a speedup claim. Unknown Defender state is
identified as an uncontrolled condition. Each trial records whether it is the
first or a later pass; the program does not claim to flush the Windows disk cache.
Synthetic data and scenario versions make runs reproducible, but host load and
cache conditions still affect elapsed time.

The quick campaign is a working check and a first measurement, not a statistically
stable forecast for the historical 88.48 GiB / 5,151,949-file backup. The thorough
mode provides repeated trials on the user's actual Windows machine. Earlier
24–32% and 20–38% gains predate durable checkpoints and must not be reused as
measurements of this final release. No two-hour restore guarantee is made.

No operation in this acceptance process uses the user's original backup,
personal conversations, actual Windows profile or private project data. The
tests do not change real Defender settings. UAC display and enterprise policy
outcomes depend on the user's Windows environment.

## Final evidence

Pending the consolidated Windows build on this branch. Consult the workflow
run attached to the exact commit before treating these sources as a tested
Windows release.
