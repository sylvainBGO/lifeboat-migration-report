# Current-format performance pass and remaining features

## Scope and source
Base: dkwolf1/Codex-Lifeboat v3.4.11, commit `4fe9724ccb54422455544e56b54399fa2bc94bc3`, under the upstream MIT license.
Candidate production commit: `1bbdfab` in the local performance worktree.
Reproducible public patch: [restore-first-pass.patch](../optimizations/restore-first-pass.patch). Its historical filename now contains the complete performance pass, not just the first two changes.
The existing backup format and restore journal semantics remain in use. This is source integration; no new user-facing recovery EXE is being advertised.

## Implemented decisions
| Area | Change | Preserved behavior |
| --- | --- | --- |
| Manifest selection | One temporary SQLite index shared by staging and final verification; stream final project hashes | Same expected content and duplicate-row mapping semantics; validation still rejects malformed backups |
| Space probes | Budget bytes and filesystem allocation overhead; resample by time, count, volume and budget | Pending-write checks plus upstream reserve; normal write errors and rollback |
| Project copies | Four native copy2 workers, at most eight queued copies, directory creation once per directory | Metadata-preserving native copy; staging before activation; all workers drained before rollback |
| Content verification | Up to four bounded readers; ordered results and errors | All SHA-256 checks retained; large files retain coordinator byte progress; total simultaneous readers capped at four |
| Package inventory | Share membership and forbidden-path enumeration; remove the second complete lowercase path set | Initial and final file-set checks; detect new forbidden empty runtime directories |
| Conversation/path rewriting | Fast prefilter skips ordered replacement loops when no old path is present | Exact ordered replacement and cascading semantics, including Unicode and escaped characters |
| Temporary storage | Close and remove index before rollback or final journal/report installation | Cleanup errors recorded without blocking recovery or replacing the primary error |

The index uses an 8 MiB SQLite cache target, not an 8 MiB process-memory limit. One staged project's inventory still occupies RAM; the source validator still holds its manifest dictionary and file-membership sets. The queue size does not grow with the number of files.
The current space reserve is still upstream's **1,000,000,000 bytes**. The separately requested **500,000,000-byte automatic pause** belongs to the resumable-operation feature, not this optimization.

## Windows evidence
Final Windows run passed: **24 targeted tests**, **97/97 upstream source regression flags**, and **12/12 timed synthetic restores**. The source GUI check runs (not a frozen-build skip). Targeted tests include worker failure, same-size staging corruption, corruption after activation, forbidden empty runtime directories introduced during validation, mixed large/small hashing, and index cleanup errors before rollback.

[Final Windows run](https://github.com/sylvainBGO/lifeboat-migration-report/actions/runs/41692844819). Local portable suite: 28 passing tests; seven Windows-only tests skipped locally and executed successfully in Windows CI.

Comparison uses the pinned original in a separate process from the candidate. Sequence per profile: original, candidate with serial hashes, candidate with four readers, candidate with four readers, serial-hash candidate, original.
The timed operation includes source validation, safety preparation, restore and final verification; backup construction is outside the timer. Native metadata copying remains enabled.

| Scenario | Original median | Final candidate median | Reduction |
| --- | ---: | ---: | ---: |
| 5,000 added small files / 40 project roots | 25.989 s | 17.594 s | 32.3% |
| Eight added 16 MiB files | 0.900 s | 0.561 s | 37.6% |
| Path-rewrite CPU microcase | 0.07576 s | 0.01304 s | 82.8% |

The preceding complete run measured **24.0%** and **20.3%** reductions respectively. Thus the observed range across the two CI runs is about **24–32% for small files** and **20–38% for the short large-file case**. The latter runs in under a second and is particularly sensitive to noise. Do not interpret the best number as a universal gain.

Small-case space probes: **5,049 → 86** in both runs. Four hash readers add little over the serial-hash candidate on the final small-file run, but substantially reduce staged/final large-file verification; bounded four-reader operation is retained. Rewriting outputs remain byte-for-byte equivalent to the reference text operation.

The small scenario has 5,000 added 1 KiB files across 40 project roots. The large scenario has eight added 16 MiB files. Both also include the upstream conversations, compressed rollout, attachment, SQLite and local-authentication fixtures.
Text rewrite timing is a separate CPU microcase: 4,000 lines, 120 mappings, 90% of lines with no mapped path. It does not predict total conversation-restoration duration.
Raw results: [performance-comparison-windows.json](performance-comparison-windows.json).

Only two observations per variant; cache, background work and CI storage introduce variance. Defender state was not sampled or changed. These results do **not** establish a two-hour restore for the user's 88.48 GiB / 5,151,949-file backup and are not a linear forecast from the historical 48-hour incident.

## Optimizations intentionally not enabled
- Do not skip final hashes based on staging alone. A later-write fault-injection test proves that final verification must still reject modified project content.
- Do not suppress portable-profile/project copies solely because destination names overlap. Reviewed ownership and content can differ, and text transformations change bytes.
- Do not replace native copy2 with a Python fused copy/hash loop: the user's Defender-off measurements did not show a win.
- Do not change to ZIP/block containers in this pass. The earlier archive microcase had different metadata guarantees; a new archive format requires its own specification and compatibility work.
- Do not replace transactional directory rename: upstream already does it.

These are explicit decisions for the current-format implementation, not unimplemented blanket optimizations claimed as complete. Additional architecture work may be necessary if a real full-size run still misses the desired duration.

## Next implementation phase: user-facing and recovery features
1. **Pause and durable resume:** manual pause; automatic pause at 500 MB; persistent reloadable plan; no repeating completed work after restart. Include temporary-index and in-flight-write accounting. Analysis/preparation remains usable below the restore threshold where its own small writes can succeed.
2. **Honest progress:** preflight visibly first, global and per-stage bars, files/bytes, throughput, elapsed time and useful remaining-time estimates; fixed layout with stable dots/labels; distinct running/waiting/paused/failed/completed states.
3. **Defender flow:** explicit user action with Windows elevation, actual-state verification, hourly check, nonmodal prompt on reactivation while the worker continues, manual fallback if policy/tamper protection blocks it, reminder to reactivate at the end. No automatic repeated disable or automatic reactivation.
4. **Diagnostics and reports:** timings and operation counts per stage, peak/free-space explanations, exact failed operation, persistent recovery state, anonymized export. Preserve standard Lifeboat reporting, archival and retention after resume.
5. **Post-migration assistance:** explain the current paths centrally. Treat sequential first opening of recent conversations as an experimental application-integration idea, not a supported preload API or an implemented feature.

A final packaged Windows release and its acceptance test follow integration of those features. No further exploratory benchmark campaign is requested from the user now.
