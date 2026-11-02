# Lifeboat: verified nested project restoration

Unofficial general-purpose fix based on official v3.4.7, commit
32ae7df2c5c56b5c5974138b4f6f2e383fbe6c5d. Includes official ZST and duplicate fixes.
No private data, hardcoded project names or backup edits.

## Behavior

Older backups can contain a project root and separately captured nested roots.
Previously location mapping rejected all overlaps. This patch accepts strict
nesting only when source and destination hierarchies match and the parent subtree
and child snapshot have identical file inventories, sizes and SHA-256 hashes.
The outermost root is staged and verified once, each child is also verified inside
that stage, then a single transactional directory swap activates the group.
All project/conversation identities remain registered. Recovery rolls back the
whole tree. Space estimates and write sets count the group once.

Equal targets, unrelated source mappings, divergent snapshots, incomplete hash
inventories and incompatible parent/child review decisions remain blocked before
project writes. The error identifies the projects and example differing files.
No timestamps decide a winner. Both divergent copies remain in the original backup.
Independent per-child archive decisions are intentionally unsupported in a group.
This fix does not silently merge genuinely divergent trees.

## Usage (FR)

Fermer Codex. Extraire entièrement ce ZIP dans un nouveau dossier. Lancer
Codex-Lifeboat-LongPaths-3.4.7.exe et sélectionner la sauvegarde existante dans Restore.
Examiner le plan proposé, puis restaurer. Après succès, utiliser Verify restore.
Ne pas modifier les manifestes de la sauvegarde. Les anciennes copies restent intactes.
Si une différence réelle entre copies est signalée, conserver le rapport :
ce build s'arrête sans choisir une version arbitrairement.

## Reproduce / review upstream

Apply nested-projects.patch to the pinned official commit with git apply.
Run python -m unittest discover -s tests -v on Windows, then the upstream
--self-test (including its automated compatibility matrix). The workflow also
runs the packaged executable self-tests and includes their JSON evidence.
Linux isolated filesystem tests adapt only Windows path resolution; the full
backup/restore/database round-trip is Windows-only and is mandatory in CI.

## Long paths and interface follow-up

Uses explicit Win32 extended paths for filesystem operations without changing
Windows registry settings. Display paths and portable manifest references retain
ordinary syntax. Includes deep-path backup, independent validation, restore,
post-restore verification and rollback tests. CI runs with LongPathsEnabled=0.
UNC prefix conversion is unit-tested; a real network-share round trip is not.
Individual filename limits and filesystem permissions still apply.

Technical details now remain reachable through a scrollable page at small window
sizes. A real Tk Windows test opens/closes the panel and verifies visible log
content. Pre-restore validation messages are forwarded to the interface; not every
filesystem traversal has a numerical percentage yet.

This build does not disable antivirus. User backup migration is not yet confirmed;
the tests use synthetic data. Do not run it while another restore or backup-folder
move is active. Do not edit backup manifests to bypass validation.
