# Durable staging-copy checkpoints — implementation status

This is the first recovery-feature increment after the current-format performance
pass. It is **not yet a user-facing pause/resume release**. The normal
`restore_backup` entry point does not activate these checkpoints; its existing
rollback behavior and 1 GB reserve remain unchanged until transaction-level
integration is complete. No executable is being distributed for this increment.

## Implemented

- An optional on-disk SQLite checkpoint for a single source/staging pair.
- Manual pause requests via a thread-safe event. The coordinator stops submitting
  copies, drains admitted native writers, records successful copies, commits, and
  then raises a distinct `RestorePaused` signal.
- Low-space adapter with a **500,000,000-byte** reserve, plus the bytes and
  allocation cost of the pending and in-flight files. It pauses before admitting
  a write whose estimated cost would consume the reserve. This is an estimate,
  not a filesystem reservation against other processes.
- A reopened checkpoint skips recorded copies. It does not reread or hash their
  content. Enumeration of the source tree still occurs; final verification is
  still required and must remain in the full restore workflow.
- OS-level single-writer lock, released on normal close or process termination.
- Batched durable SQLite commits, FULL synchronization and bounded cache. A
  graceful pause commits all completed writes. Abrupt process termination may
  replay the uncommitted batch (at most 255 rows with the default batch size)
  plus the bounded worker queue (at most eight copies).
- Original Windows short-name root spelling accepted without resolving each file.

The ledger certifies that the copy call succeeded, not that a file passed content
verification or that a power failure cannot lose cached filesystem writes. It
requires an exclusively owned staging directory. It must not be reused as a
general-purpose skip list for arbitrary user-modified files.

## Tests

Eight new tests cover manual pause and reopen, low space before writing, low
space with an admitted copy, exact reserve arithmetic, write failure during
pause, wrong operation binding, exclusive ownership, and abrupt child-process
termination with an unfinished SQLite transaction. The child-process test caught
the Windows short-path mismatch; that production defect has been corrected.

Local suite: 25 passing tests, seven Windows-only integration tests skipped
locally. Windows CI applies the published performance patch and then this feature
patch to pinned upstream v3.4.11. It runs all 32 targeted tests and the official
source regression, including GUI and rollback.

**Windows result: 32/32 targeted tests and 97/97 official regression flags passed.**
[Successful run](https://github.com/sylvainBGO/lifeboat-migration-report/actions/runs/41701880398),
tested public commit `2efad57d8422a2fe0a2050fc91c3dcb6033615aa`,
production source commit `ced0080` in the local performance worktree.
[Incremental source patch](https://github.com/sylvainBGO/lifeboat-migration-report/blob/main/features/resume-copy-foundation.patch)
applies after the previously published performance patch.

No new performance claim is made
for checkpointed copies; durable bookkeeping has a cost that remains to be
measured once full integration is complete.

## Required before exposing the pause button

1. Catch `RestorePaused` before the normal rollback handler and persist an
   operation-level paused state. Do not wire the component into the current
   generic exception handler, which would otherwise roll back a pause.
2. Reuse project staging/quarantine/activation records across restarts, including
   interruption between rename and journal update. Never regenerate transaction
   paths for an existing project transaction.
3. Add durable phase and file checkpoints for conversations, portable profile,
   attachments and database installation. Directory clearing must happen once;
   resuming must not delete already completed files.
4. Provide the reloadable operation document and GUI pause/resume controls,
   then connect explicit progress states and standard reports/retention.
5. Test the complete restore across interruptions at each transactional boundary
   on Windows before packaging a user-facing executable.

The preparation/analysis stage must remain independent of the restore pause
threshold. A checkpoint can be opened below 500 MB if its own metadata writes
succeed; the low-space adapter runs only before copy admission.
