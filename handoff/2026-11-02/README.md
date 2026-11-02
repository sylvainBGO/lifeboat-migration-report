# Dossier technique Lifeboat — migration et reprise, 2 novembre 2026

Ce dossier accompagne le retour détaillé destiné à l'issue https://github.com/dkwolf1/Codex-Lifeboat/issues/8. Il n'a pas été publié ni envoyé automatiquement.

## Résultat et portée

Backup : 88,48 Gio, 5 151 949 fichiers, 713 conversations, 40 identités de projets. La première restauration dérivée de v3.4.7 a échoué après environ 48 h 38 (temps affiché, contrôle préalable inclus). La reprise spécifique a terminé le 2 novembre 2026 à 11:25:23 UTC. Le résultat vérifié est : 713 identités attendues et présentes, 712 conversations actives dans l'index, SQLite quick_check OK, 146 sessions réutilisées, 567 réécrites, 42 pièces jointes copiées, 37 groupes de projets réutilisés, 40 identités enregistrées.

La vérification finale de secours est ciblée. Les projets et l'audit de portabilité n'ont pas été reparcourus. Les 302 références de pièces jointes du plan comprennent seulement 42 références marquées présentes. Succès de la reprise ne signifie donc pas récupération de toutes les anciennes pièces jointes ni nouvelle vérification intégrale de tous les projets.

## Contenu

- `sources/` : tous les fichiers suivis par Git de notre version finale, avec code, tests, documentation, licences et scripts de construction. Aucun dossier `.git`, historique de conversations ou donnée d'authentification n'est inclus.
- `patches/cumulative-v3.4.7.patch` : toutes nos modifications depuis la base officielle v3.4.7.
- `patches/rescue-only.patch` : uniquement la reprise, après notre version LongPaths ; ce patch n'est pas autonome sur v3.4.7.
- `patches/local-commits.txt` : identifiants et sujets des commits locaux.
- `windows/` : trois ZIP historiques exacts (Nested, LongPaths, Recovery). Ils sont fournis pour comparaison et reproductibilité, pas comme trois étapes à exécuter.
- `build/` : workflow original, patches, notices, checksums et rapports extraits des trois ZIP.
- `evidence/` : extraits anonymisés réels, trace des deux exceptions ENOSPC, fin de journal de reprise, synthèse du plan préparé et rapport final.
- `MESSAGE-ACCOMPAGNEMENT.md` : message complémentaire prêt à joindre au retour détaillé.
- `DIAGNOSTIC-ET-CORRECTIONS.md` : mécanisme d'échec, corrections, limites et propositions.
- `SHA256SUMS.txt` : empreintes des fichiers du dossier (hors ce manifeste lui-même).
- `PACKAGE-CHECKS.json` : vérifications du dossier et de l'application du patch, distinctes des tests historiques du programme.

Les trois exécutables correspondent aux artefacts conservés dans cet environnement. Ce dossier ne contient pas une reconstitution de l'ancien build de backup basé sur v3.4.5 : ses résultats étaient déjà expliqués dans l'issue, mais ses sources exactes ne sont pas présentes dans cet instantané local.

## Provenance et reconstruction

Base officielle : `32ae7df2c5c56b5c5974138b4f6f2e383fbe6c5d`.
Commit local final : voir `evidence/provenance.json`.
Build de secours vérifié : https://github.com/sylvainBGO/OLGA-LIVETRACK/actions/runs/41415943242.

Le workflow historique est conservé sans modification. Il attend un fichier `lifeboat-rescue-build/rescue.patch`, clone la version officielle dans `lifeboat/`, vérifie le SHA de base, applique le patch, exécute les tests Windows et construit l'exécutable avec PyInstaller. Le dossier `build/Codex-Lifeboat-Recovery-Windows-x64/rescue.patch` contient le patch effectivement livré avec l'exécutable. Pour réutiliser le workflow dans un autre dépôt, le placer à l'emplacement qu'il attend et adapter uniquement son déclenchement de branche.

Pour examiner les sources complètes, utiliser directement `sources/`. Les sources sont identiques au commit final ; aucune substitution de chemins n'a été effectuée dans le code.

## Tests historiques confirmés

Les fichiers dans `build/Codex-Lifeboat-Recovery-Windows-x64/` contiennent :

- `rescue-tests.txt` : 36 tests réussis sous Windows ;
- `official-self-test-result.json` : 87/87 contrôles, matrice automatisée 12/12 ;
- `packaged-smoke-test.json` : démarrage empaqueté réussi, version de plan 1, réserve 500000000 octets ;
- `SHA256.txt` : empreinte de l'exécutable distribué.

Ces tests utilisent des données synthétiques. Le rapport anonymisé réel constitue une preuve distincte. Aucune nouvelle restauration réelle ni nouvelle construction Windows n'a été lancée pour produire ce dossier.

## Précautions de lecture et anonymisation

Le rapport est un extrait par liste blanche, et non une copie exhaustive. La synthèse du plan est celle du plan préparé AVANT exécution : ses tâches encore `pending` ne contredisent pas le rapport final `complete`. Elle n'est pas rechargeable dans le programme. Les chemins, titres, identifiants de conversations et projets, contenus de conversations et données privées ne sont pas fournis. Les empreintes des fichiers originaux privés sont conservées uniquement pour tracer la provenance.

Les horodatages, compteurs, statuts, noms de fonctions et traces de code sont conservés. Le compte GitHub public servant à citer le build reste visible. Une annexe PDF de 34 captures, classees par phase et anonymisees, est jointe dans screenshots/. Les images privees originales ne sont pas jointes. Les mesures ne sont pas attribuees a une phase precise sans preuve commune.

Les notices historiques restent inchangées : notamment, la phrase « Aucune restauration réelle n'a encore été exécutée » dans la notice de secours était vraie lors du build, mais est désormais dépassée par le rapport final du 2 novembre joint ici.

L'outil Recovery est réservé à l'incident décrit (profil initialement vide, projets terminés, arrêt dans _restore_sessions, absence de rollback). Il ne doit pas être utilisé comme reprise universelle.
