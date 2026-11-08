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
| Window layout | Compact responsive controls and a scrollable central panel keep progress, results and the activity log reachable. Startup dimensions adapt to the Windows work area, including title/borders and taskbar. Physical captures verify visibility; a separate logical 1080 × 720 layout check remains. |
| Project archives | Optional production `archive-blocks-v1` backup storage, format 2.5. Direct block creation and extraction into the existing staging tree; logical file SHA-256 plus physical block hashes; exact supported timestamps/modes and empty directories; resumable extraction. Ordinary file backups remain the default. |
| Local conversation pre-read | Optional bounded read of up to 50 recent local rollout files. It warms temporary OS file cache only. It does not load a persistent Codex application cache, call an agent or open a conversation through the app. |
| Benchmark delivery | Windows launcher with quick/thorough modes, versioned synthetic scenarios, space check, stop after the current trial, isolated original/final workers and JSON plus readable text reports. |
| Actual final performance | Compare the original upstream restore with the final durable recovery path and its archive variant. Measure backup creation, comparison-plan construction, preparation, execution and combined elapsed time. Production process guards and integrity checks stay inside their corresponding phase timings. |

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
- Packaged application open/close, plus synthetic screenshots and minimum-size
  layout bounds for controls, progress, results and the activity log.
- Benchmark contracts, synthetic UI verification and a bounded quick campaign
  through the packaged original and final workers, including the production
  archive format.

Branch builds publish review artifacts only. The main-branch job publishes a
prerelease only after every required check has passed. The release includes the
application ZIP, benchmark ZIP, source ZIP, build provenance and SHA-256 checksums.
The benchmark workflows remain available for explicitly requested supplementary
campaigns rather than automatically repeating this acceptance gate.

The completed Windows gate ran 116 component tests: 115 passed and one extended-
attribute test was unavailable on Windows. All 29 benchmark contracts passed.
The exact published build and its complete acceptance record are linked below.

## Performance interpretation

The current protocol is `2026-11-production-path-2` (report schema 4). It includes
the production guards during backup creation, comparison-plan construction and
restore preparation, plus the additional execution guard of durable resume.
Synthetic fixture conflicts are resolved through the normal decision APIs;
these automatic choices are restricted to the benchmark's owned source and
target directories. Human decision time and worker startup are excluded.

The first branch campaign used an earlier protocol which omitted common planning
and process checks. Its absolute times and percentages are not interchangeable
with this protocol, and the new tool rejects mixed-protocol comparisons.

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

**Community Recovery 23 was published and its assets were verified on November 8, 2026.**

- [Release and three ZIP downloads](https://github.com/sylvainBGO/lifeboat-migration-report/releases/tag/community-recovery-23)
- [Published source commit](https://github.com/sylvainBGO/lifeboat-migration-report/commit/b4cc981ceb02a40796c927c102bfbcab5fb703ad)
- [Successful main Windows run](https://github.com/sylvainBGO/lifeboat-migration-report/actions/runs/42512089907)
- [Merged implementation PR](https://github.com/sylvainBGO/lifeboat-migration-report/pull/1)
- [Machine-readable acceptance record](../results/community-recovery-23/acceptance.json)
- [Complete benchmark JSON](../results/community-recovery-23/benchmark.json) and [readable report](../results/community-recovery-23/benchmark.txt)

The gate passed 115 component tests (one additional test is unavailable on
Windows) and all 29 benchmark contracts. Both the source and packaged application
passed 97 regression checks and 12 compatibility scenarios. Packaged ordinary-file
and archive pause/reopen recovery, local pre-read of three synthetic files, and
GUI open/close passed. Physical UI bounds were verified inside a 1024 × 720 Windows
work area, including navigation, language selection, recovery controls and results.

All 12 packaged quick campaign trials completed with valid results. All six full
restore trials preserved the destination conversation, authentication and installation
identity; source and backup content remained unchanged. Each restored database
contained the expected four conversation identities and three active index entries.

The application, source and benchmark ZIPs passed ZIP integrity checks. Their SHA-256
values matched both the workflow checksum manifest and GitHub's published release
asset digests. Build identities point to the exact source commit and main workflow
above. Defender mutation and UAC-command contracts were tested with mocks; no real
protection setting was changed by the acceptance process.

### Measurements from the published build

Protocol: `2026-11-production-path-2`; fixture: `2026-11-final-2`. One trial per variant
and profile, Windows CI, cache not flushed. Defender was observed disabled at every
sampling point. This campaign does not compare protection enabled and disabled.
The listed added files are in addition to the common Codex/SQLite/conversation fixture.

| Added workload | Variant | Backup (s) | Full restore (s) | Backup + restore (s) |
| --- | --- | ---: | ---: | ---: |
| 200 × 1 KiB, 4 projects | Upstream v3.4.11 | 1.312 | 1.900 | 3.212 |
| 200 × 1 KiB, 4 projects | Final ordinary files | 1.131 | 3.065 | 4.196 |
| 200 × 1 KiB, 4 projects | Final archive blocks | 1.295 | 4.445 | 5.740 |
| 2 × 1 MiB, 1 project | Upstream v3.4.11 | 0.632 | 0.945 | 1.576 |
| 2 × 1 MiB, 1 project | Final ordinary files | 0.642 | 2.297 | 2.940 |
| 2 × 1 MiB, 1 project | Final archive blocks | 0.989 | 2.290 | 3.279 |

The final ordinary-file path is slower than upstream on both of these very small
workloads. The archive path also has a higher combined backup-plus-restore time
than final ordinary files in both profiles. The 0.008-second difference in restore
time for the two-file profile is too small and too sparsely sampled to establish
an archive speedup. No quantified cause is inferred without profiling.

The benchmark now measures the complete production path and exposes these costs.
It does not establish a speed improvement on ELISYNK, a persistent Codex cache
preload, or a duration for the historical 88.48 GiB / 5,151,949-file backup.
The packaged thorough mode can produce repeated measurements on the actual Windows
machine without using its personal backup.
