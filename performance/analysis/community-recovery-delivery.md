# Community Recovery delivery — acceptance record

This community derivative keeps the upstream v3.4.11 backup format and MIT license.
Pinned upstream: `4fe9724ccb54422455544e56b54399fa2bc94bc3`.
Implementation: local `a12582c`; reproducible public source commit
`5d90e04c973b8725af73141df813a5e05c8114a6`.

## Delivered scope

| Request | Implementation |
| --- | --- |
| Reduce repeated work | Shared indexed manifest, bounded native copy/hash workers, batched space probes, path-rewrite prefilter; completed tasks reused on resume |
| Manual pause and restart | Pause button; durable `resume-plan.json` linked to the original recovery point; reload after process or computer restart |
| Low-space handling | 500,000,000-byte reserve plus pending data/allocation; admitted copies drained; expanded conversation output budgeted before writing; actual ENOSPC preserves resumable state |
| Transaction continuity | Preserve original staging/quarantine/activation paths, one-time directory clears, database-install intent; recover rename-before-journal interruption |
| Integrity and normal lifecycle | Initial validation once, stage verification, mandatory final verification, normal identity/lineage registration, recovery retention and standard report |
| Truthful progress | Initial control appears before project copying; overall workflow bar and separate stage bar; known files/bytes and stage rate; unknown totals are indeterminate |
| UI stability | Fixed indicator geometry, no varying-length ellipsis animation, explicit paused state surviving refresh, resizable activity log |
| Defender | Explicit UAC request and actual-state check; hourly observation; nonmodal reactivation prompt; restore continues; manual reactivation reminder |
| Diagnostics | Cumulative phase durations, exact current task, free/pending/allocation/reserve figures; local detail and allowlisted shareable summary |
| Migration assistance | Generated `MIGRATION-PATHS.md` with actual old/new profiles and centralized instructions; no recreation of the old profile |
| Delivery | Windows executable, complete source archive, build identity, SHA-256 checksums and French usage guide |

The named patch `features/resume-copy-foundation.patch` now contains the complete
integrated feature change, applied after `performance/optimizations/restore-first-pass.patch`.
Its historical filename does not describe an incomplete implementation.

## Acceptance evidence

Final Windows workflow: https://github.com/sylvainBGO/lifeboat-migration-report/actions/runs/41713076881

**Final result: success on Windows Server 2025, Python 3.12.10.**

- 52/52 targeted tests passed, including the expanded-output reserve test.
- 97/97 upstream source regression flags passed.
- 97/97 packaged regression flags and 12/12 automated compatibility scenarios passed.
- Packaged pause/reopen recovery passed, with completed projects not recopied,
  final verification, reports/retention and migration guide all confirmed.
- Packaged GUI opened and closed normally. The check follows the actual window
  process, rather than mistaking PyInstaller's onefile parent for the GUI process.
- Synthetic Windows screenshots were retrieved and inspected for initial-check
  and conversation-stage states; these are not captures of a real user restore.
- Downloaded Windows and source ZIPs passed archive integrity and published SHA-256
  checks. `BUILD.txt` points to the tested commit and run above.

Release: https://github.com/sylvainBGO/lifeboat-migration-report/releases/tag/community-recovery-14

| Asset | SHA-256 |
| --- | --- |
| Windows ZIP | `43a28644ced338a1fb97767fa7ae724231bf61894d4d2c6b9dc11a4e916e2e15` |
| Sources ZIP | `760b6ef3f4b844376bf36d7828d138bebf9e25803ed2a4833dd247a8e30914ac` |
| Executable | `c6e6e40ec605ee520a55e3c1a1897d6c576d571dab5723f478ac5cc7b0c1bfba` |

Automated checks are preserved in `community-recovery-acceptance.json`. The original
workflow artifact includes the complete synthetic reports and screenshots. Manual
physical-device statuses inherited from upstream are not tests of this community build.

## Limits retained explicitly

- No two-hour result is established for the historical 88.48 GiB / 5,151,949-file
  backup. Prior performance measurements predate durable checkpoints: approximately
  24–32% less time on small-file synthetic restores and 20–38% on a short large-file
  case. They are not full-volume forecasts and are not newly measured release gains.
- ZIP/block storage is not introduced. Final integrity checks are not removed.
- Native copy, SQLite transactions and directory operations stop at safe boundaries,
  not mid-system-call. Free-space accounting is an estimate, not an OS reservation.
- Graceful pauses commit completed work. Abrupt termination may replay at most the
  uncommitted batch (255 project entries plus the bounded queue, or 63 sequential
  tasks). An interrupted verification may reread its stage.
- Keep the backup, original recovery point and staged/restored data unchanged while
  paused. The plan alone cannot replace its checkpoints or source data.
- This new resume schema does not import the bespoke 3.4.7 incident recovery plan.
- First-opening recent conversations sequentially remains a documented experimental
  idea; no supported persistent preload API or automatic 50-chat warmup is claimed.
- Defender UAC invocation, cancellation/state contracts and nonblocking GUI behavior
  are tested with mocks. CI does not change Defender settings or bypass policy.
- The executable is unsigned. Synthetic fixtures contain no user backup, chats,
  secrets or project files; no operation was run on the user's real restored profile.

The earlier foundation and performance-pass documents are historical milestones;
this record supersedes their lists of pending recovery/UI work.
