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
Codex-Lifeboat-Nested-3.4.7.exe et sélectionner la sauvegarde existante dans Restore.
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
