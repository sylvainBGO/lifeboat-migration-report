# Lifeboat Recovery — reprise spécifique 3.4.7

Cet outil termine une restauration 3.4.7 interrompue dans `_restore_sessions`,
après copie complète des projets et du profil portable vers un profil initialement
vide. Il ne remplace pas le Restore général et ne doit pas être utilisé pour un
autre point d'échec.

## Utilisation

1. Fermer Codex et l'ancien Lifeboat. Extraire le ZIP dans un nouveau dossier.
2. Ouvrir `Codex-Lifeboat-Recovery.exe`.
3. Sélectionner le `restore-journal.json` original et le fichier texte contenant
   la trace complète de l'erreur. Le chemin du point de récupération de cet incident
   est proposé par défaut ; corriger si nécessaire.
4. Choisir où enregistrer `reprise-plan.json`, puis **Préparer le plan**.
   Cette étape fonctionne sous 500 Mo : seules les métadonnées et les listes de
   conversations sont lues. La base temporaire subit un quick_check SQLite.
5. Conserver le plan. Ne pas modifier/déplacer les dossiers source/destination.
   Attendre la fin de la préparation avant un redémarrage de Windows.
6. Après ajout d'espace, rouvrir l'outil, **Charger un plan**, puis **Reprendre**.
   Aucun inventaire ou contrôle de chemins n'est répété.

Le plan contient des chemins et métadonnées privés : ne pas le publier.
Il reste nécessaire de conserver le backup source et le point de récupération.

## Ce qui est évité

- Pas de validation préalable des 88 Gio ni de lecture de `sha256.csv`.
- Pas de recopie/contrôle des groupes de projets déjà terminés.
- Pas de recopie du profil portable, ni de suppression globale des sessions.
- Pas de copie de l'index source immédiatement suivie d'une reconstruction :
  l'index est construit une seule fois depuis la base finale.
- Pas d'audit final récursif de portabilité. Le rapport indique cette limitation.

Le parcours rglob original n'a pas d'ordre garanti. La préparation ne s'appuie
pas sur le nom/date de la conversation pour déduire ce qui est terminé : elle
réutilise les fichiers définitifs présents dans `sessions`, car l'ancien code a
supprimé ce dossier au début puis finalisé chaque fichier par remplacement atomique.
Le fichier correspondant au temporaire est toujours recopié. Les archives ne sont
pas présumées terminées : cette phase n'avait pas commencé.

Cette confiance est spécifique à l'incident et suppose que les dossiers sont
restés inchangés. Les projets ne sont pas revérifiés, même les six groupes internes
que la copie ultérieure du profil a pu réécrire.

## Manque d'espace et interruptions

Réserve : exactement 500 000 000 octets. Seule l'exécution est soumise au seuil.
Les écritures de fichiers sont découpées en blocs avec contrôle de l'espace avant
chaque bloc, y compris les grosses lignes JSONL. Un supplément couvre le bloc en
cours et les buffers ; l'arrêt peut donc intervenir légèrement au-dessus de 500 Mo.
Le disque peut encore se remplir brutalement à cause d'un autre processus : ENOSPC
reste traité et ne déclenche jamais de rollback.

Le fichier interrompu n'est pas validé ; la prochaine reprise le recommence.
Les points terminés sont enregistrés atomiquement après chaque fichier/étape.
Si l'enregistrement lui-même échoue, le dernier plan valide reste utilisable ;
au pire la dernière opération est répétée, sans effacer les autres fichiers.
La petite base préparée est conservée et installée par copie atomique pour rendre
cette étape rejouable après une coupure.

Il n'y a pas de pause manuelle dans cette version. Ne pas fermer pendant le travail.
Le verrou empêche deux exécutions de secours simultanées pour le même point.

## Finalisation

L'outil réutilise les routines natives de paramètres portables, index, validation
SQLite/identifiants des conversations, registre des projets, lineage, rapports et
rétention conservatrice des points de récupération. Les contrôles projets et le
parcours complet de portabilité sont explicitement sautés. Le journal original est
complété avec une section `rescue` ; le rapport final est dans `Documents/Codex Restore Reports`.
Le plan est marqué `complete` après les étapes de finalisation.

L'interface est une fenêtre de secours distincte avec activité, compteurs et
état d'interruption. Elle ne simule pas les anciens pourcentages 62 % / 94 %.

## Construction et tests

Base officielle v3.4.7 : `32ae7df2c5c56b5c5974138b4f6f2e383fbe6c5d`,
avec le patch LongPaths/projets imbriqués puis le patch de secours.
Le workflow Windows exécute les régressions, les auto-tests officiels et le test
de démarrage de l'exécutable. Les données de test sont synthétiques.
Aucune restauration réelle n'a encore été exécutée avec cette version.
