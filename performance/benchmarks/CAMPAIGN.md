# One-run Windows campaign

Run `Lancer-Campagne.cmd` after extraction. Submit only the resulting
`results/campagne-lifeboat-*.json`. No Python installation or administrator rights
are required. At least 3 GB free space is required. The campaign never changes
Defender and never accepts a personal backup or restore destination.

Ten isolated child scenarios run sequentially. Each has a 30-minute time limit.
A failed scenario is recorded and subsequent scenarios continue. Ctrl+C stops
the active child and preserves completed results. Temporary test data is cleaned.
A force kill or power failure can leave a `lb-campaign-*` test directory.

## What is tested

- Real Lifeboat v3.4.11 backup, prepare and restore code (pinned upstream commit
  4fe9724ccb54422455544e56b54399fa2bc94bc3) on synthetic profiles: many small files,
  larger files, and nested/overlapping project and portable-profile roots.
- Each real restoration compares original staging manifest lookup against an
  experimental per-run SQLite index. Source hashes and final verification stay
  enabled. Baseline runs first: warm-cache bias remains.
- Original source/target fixtures include JSONL and compressed ZST conversations,
  an attachment, SQLite schema migration, preserved target authentication and
  disposable paginated history. The test does not reconstruct a 713-chat backup.
- 100k and 1m-row manifests, 40 project prefixes, index construction included.
- Six copy/archive strategies on three compression profiles; ZIP preparation is
  separate, and ZIP/file-metadata-free cases are NOT metadata-equivalent restores.
- copy2 with 1, 2, 4 and 8 worker threads; fixed order, synthetic payload only.
- A persistent-journal resume concept with simulated interruption and a 500 MB
  free-space threshold. This is not integrated Lifeboat production resume and is
  not a power-loss durability test.
- Official upstream self-tests including corruption, rollback, space requirements,
  identity and conversation preservation. The frozen GUI test is skipped upstream;
  Git checks use upstream fallback when Git is absent (availability is reported).

## Measurements and limits

The report retains per-scenario status, phase times and instrumented hash/copy/
rewrite calls and logical byte volumes. Backup and restore counts are separated.
Counts cover known wrappers, not every physical read. Paths renamed between
staging and activation are distinct in same-path repetition counts. Timed phases
are inclusive, so their durations must not be added. Instrumentation itself adds
some overhead. Windows peak working set and OS I/O counters cover the whole child
process, including fixture creation. They are not physical disk throughput.

No restore guard or content verification is removed. The tested corpus and
Windows CI smoke are not proof of correctness for every production backup or
of the two-hour goal. Generated test executable copies inside synthetic backups
are benchmark programs, not release Lifeboat restore applications. They are
removed with the owned scenario directory.
