# Codex Lifeboat Community — recovery and performance

**Current tested download: [Community Recovery 23](https://github.com/sylvainBGO/lifeboat-migration-report/releases/tag/community-recovery-23)**, published November 8, 2026.

- [Windows application ZIP](https://github.com/sylvainBGO/lifeboat-migration-report/releases/download/community-recovery-23/Codex-Lifeboat-Community-Windows.zip)
- [Windows benchmark ZIP](https://github.com/sylvainBGO/lifeboat-migration-report/releases/download/community-recovery-23/Lifeboat-Benchmark-Windows.zip)
- [Complete integrated source ZIP](https://github.com/sylvainBGO/lifeboat-migration-report/releases/download/community-recovery-23/Codex-Lifeboat-Community-Sources.zip)
- [SHA-256 checksums](https://github.com/sylvainBGO/lifeboat-migration-report/releases/download/community-recovery-23/SHA256.txt)
- [Acceptance record and measured limitations](performance/analysis/completion-status.md)

This is an unofficial community prerelease. Its Windows acceptance gate passed;
the small quick campaign does not establish a final-release performance gain.

The current Community build combines upstream **v3.4.11** with three versioned
patches, applied in this order:

1. `performance/optimizations/restore-first-pass.patch`
2. `features/resume-copy-foundation.patch`
3. `features/completion.patch`

It includes durable pause/resume, startup discovery of unfinished plans,
explicit Defender controls with manual reactivation reminders, optional project
archive blocks and bounded local conversation pre-reading. Pre-reading warms
only the temporary OS file cache; it is not a supported Codex application preload.

- [Windows build and acceptance workflow](https://github.com/sylvainBGO/lifeboat-migration-report/actions/workflows/restore-features.yml)
- [Community downloads and historical releases](https://github.com/sylvainBGO/lifeboat-migration-report/releases)
- [Current completion record](performance/analysis/completion-status.md)
- [Benchmark campaign and usage](performance/benchmarks/CAMPAIGN.md)

The `handoff/2026-11-02` directory below is the historical incident package. The
current program is reconstructed by the Windows workflow; do not use the old
handoff source directory as the current implementation.

## Historical migration — developer handoff

Public technical evidence for [dkwolf1/Codex-Lifeboat issue #8](https://github.com/dkwolf1/Codex-Lifeboat/issues/8#issuecomment-6588510483).

## Downloads

- [Complete handoff ZIP (54.2 MB)](https://github.com/sylvainBGO/lifeboat-migration-report/releases/download/handoff-2026-11-02/Lifeboat-Developer-Handoff-20261102.zip)
- [34 anonymized screenshots — 35-page PDF](https://github.com/sylvainBGO/lifeboat-migration-report/releases/download/handoff-2026-11-02/Captures-progression-ressources-anonymisees.pdf)
- [Release page and checksums](https://github.com/sylvainBGO/lifeboat-migration-report/releases/tag/handoff-2026-11-02)

The ZIP was reconstructed and verified on GitHub against the original SHA-256:

```
33fa6b4ecfe77c3c5ae9af831129ccde83463d785ac3aa499247c9136704dc27
```

## Browse the evidence

The dedicated [handoff/2026-11-02](handoff/2026-11-02) directory contains:

- [Complete modified sources and tests](handoff/2026-11-02/sources)
- [Cumulative and recovery-only patches](handoff/2026-11-02/patches)
- [Build workflows and test reports](handoff/2026-11-02/build)
- [Anonymized incident evidence](handoff/2026-11-02/evidence)
- [Screenshot index](handoff/2026-11-02/screenshots/index.json)

Binary builds and the PDF are in the release assets / full ZIP, not in the browsable extraction. The encoded directory contains transport chunks used for reproducible reconstruction, not additional user data. Use the complete release ZIP for the original package and its full SHA256SUMS manifest.

## Outcome and limitations

The 88.48 GiB / 5,151,949-file backup contained 713 conversations and 40 project identities. The initial restore failed after a displayed 48 h 38 min, including preflight. Incident-specific recovery completed on November 2, 2026: 713 expected/present conversation identities, 712 active index entries, SQLite quick_check OK, 146 sessions reused, 567 rewritten, 42 attachments copied, and 37 project groups reused.

Final verification was targeted: it reused prior project evidence and did not repeat the full project content or portability audits. The 42 copied attachments do not represent recovery of all 302 historical attachment references.

The historical handoff contains **unofficial, incident-specific recovery tooling**; it is separate from the current Community application linked at the top of this page. Read the report and scope restrictions before reusing code. The archive retains historical French documentation and notices as delivered; the [current issue report is in English](https://github.com/dkwolf1/Codex-Lifeboat/issues/8#issuecomment-6588510483). Statements in historical files that the package had not yet been published are superseded by this public release.

No private backup, user SQLite database, authentication material, conversation content, raw private screenshots or executable private recovery plan is included. Original upstream license files are retained in the source tree.
