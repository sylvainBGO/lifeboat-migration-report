# Diagnostic, corrections et pistes

## ENOSPC : mécanisme confirmé par la trace et le code

Première exception dans `restore_backup → _restore_sessions → _rewrite_copy`. Deuxième exception ENOSPC dans `backup.write_json → atomic_io.write_json → atomic_io.write_text`, pendant le traitement de la première. L'écriture du journal précède l'appel à `rollback_restore` ; son échec empêche d'atteindre cet appel. Le journal demeure `restoring`. Voir `evidence/failure-trace.txt`.

La base temporaire préparée faisait 4 448 256 octets. Un temporaire de session de 97 807 644 octets était présent. La copie de sécurité initiale du profil vide avait été mesurée à 77 fichiers / 8,19 Mio. Elle ne constituait donc pas à elle seule la cause de saturation. Le temps 48 h 38 est celui affiché par l'interface et inclut le contrôle préalable ; ce n'est pas le temps de copie seul.

## Corrections présentes dans les sources

- `nested_projects.py`, `location_mapper.py`, `restore_plan.py`, `restore.py` : regroupement des projets imbriqués compatibles sous une transaction parente, vérifications des sous-projets et maintien des identités. 40 identités correspondent à 37 groupes dans le cas réel.
- `fs_paths.py` et consommateurs : syntaxe Win32 étendue pour les appels système, affichage et manifestes ordinaires, gestion des chemins UNC et URI SQLite. Tests exécutés sous Windows avec LongPathsEnabled=0.
- `gui.py`, `validate.py` : accès aux détails dans les fenêtres courtes et messages du contrôle préalable. Ce n'est pas encore une correction de toute la progression 62/94 %.
- `rescue.py` : préparation unique, document JSON persistant, chargement direct, réutilisation des preuves de projets, sessions finales conservées, temporaire interrompu repris en priorité, pièces jointes copiées, finalisation native.
- `rescue_gui.py` : fenêtre distincte de préparation/chargement/reprise et compteurs d'activité. Pas de bouton de pause manuelle dans cette version.
- `restore.verify_restored(..., reuse_project_evidence=...)` : voie ciblée explicitement limitée, sans nouvel audit des projets et de portabilité.

## Sûreté de la reprise ciblée

La préparation exige un journal `restoring`, un profil initialement vide, tous les groupes projets terminés, une trace d'échec compatible, un seul temporaire et une base préparée valide. Les conflits et racines externes hors périmètre sont refusés. Elle ne déduit pas les opérations terminées de l'ordre de rglob.

Dans CET incident, le dossier sessions avait été vidé au démarrage puis chaque fichier finalisé par remplacement atomique. La présence d'un fichier définitif sert de preuve de fin sous hypothèse d'absence de modification externe. Cette preuve ne se généralise pas aux profils déjà peuplés.

Réserve : 500 000 000 octets. Préparation exemptée du seuil mais toujours dépendante d'un minimum d'espace pour enregistrer le plan. Écriture par blocs de 1 Mio, regroupement de petites lignes, contrôle d'espace tenant compte des buffers, fsync puis os.replace. Checkpoint après chaque tâche et étape. En cas d'interruption, le fichier incomplet est recommencé ; les autres tâches restent acquises. Un verrou évite les reprises simultanées. La base préparée est copiée atomiquement plutôt que déplacée pour rendre son installation rejouable.

Un contrôle d'espace ne peut pas empêcher un autre processus de consommer brutalement le disque : ENOSPC reste pris en charge. Le secours ne lance pas de rollback automatique. Les finalisations natives (paramètres, base, index, identités, lineage, journal/rapport, rétention) sont reprises après la copie.

## Performance : confirmé vs à mesurer

Les passages de validation source, copie, vérification du staging et contrôle final existent dans le code. Leur coût individuel n'a pas été profilé sur le backup réel. Les arborescences internes .codex/.chatgpt-projects peuvent chevaucher projets et profil portable : vérifier les payloads effectivement présents dans les deux parties du package. `_restore_portable_profile` supprime/reconstruit les destinations qu'il traite. Toute réécriture ultérieure limite la valeur d'une preuve de hash antérieure. Cette limite est déclarée pour notre reprise, qui ne relit pas les projets.

La réserve initialement espérée de 10 Gio n'a pas suffi. Une estimation devrait couvrir le pic d'occupation, le staging, les quarantaines éventuelles, les temporaires, la taille allouée et les effets de compression/traduction. Nous n'avons pas un bilan octet par octet permettant d'attribuer tout le dépassement à Lifeboat.

Defender : l'utilisateur confirme une forte dégradation avec la protection temps réel, sa réactivation suivie d'une baisse d'activité Lifeboat, puis une reprise nette après désactivation. Désactivation temporaire nécessaire dans ce cas pour une progression utilisable. Pas de facteur d'accélération chiffré ni de causalité démontrée sur la totalité des 48 h. Aucune désactivation automatique ajoutée dans le code. Indexeur : activité observée, contribution exacte non isolée. RAM de plusieurs Gio observée : pas de preuve de fuite mémoire.

Pistes non implémentées : contrôles d'intégrité regroupés avec la copie lorsque les garanties le permettent ; réduction des scans/manifeste répétés ; payloads compressés par blocs ; instrumentation temps/octets/IO par étape. Les blocs compressés ne suppriment pas le coût de création de millions de fichiers sur la destination. Objectif exploratoire de deux heures, sans benchmark établissant sa faisabilité.

## Interface

Barre globale figée à 62 % pendant le contrôle préalable : à 17 h 13 affichées, validation 96,6 %, 5 135 838/5 151 949 fichiers, 85,50/88,48 Gio. Vers 21 h 30 affichées, contrôle des relations/historique. Barre à 94 % pendant staging et remplacement du profil. Certaines étapes de copie étaient cochées avant la fin du précontrôle. Les points animés et variations de texte déplaçaient la mise en page. Restant « Calculating... », débit absent, état Ready après erreur. Captures fournies par l'utilisateur, observations non profilées par fonction.

Propositions : ordre réel contrôle/copie/vérification ; barre globale et sous-barre ; compteurs utiles même sans ETA ; état pause/échec/incomplet distinct ; géométrie stable ; pause manuelle et réserve d'espace avant épuisement.

## Après restauration

Ouverture de Codex, conversations visibles, reprise de tâches et retour d'une commande au nouveau chemin de base. Certaines références Git/worktrees ont nécessité une correction. Les anciens messages conservent des chemins historiques : ajout d'instructions communes de migration. Présence de secrets ne prouve pas déchiffrement sur nouvelle machine. Lenteur après lancement de plusieurs chats, sans démonstration de corruption de restauration.

Premier chargement long, puis retour rapide aux conversations testées, y compris après fermeture/réouverture de l'application. Piste uniquement : lecture séquentielle des conversations récentes via https://learn.chatgpt.com/docs/app-server (`thread/list`, `thread/turns/list`, `thread/items/list`). Le bénéfice pour le cache de l'interface depuis un processus séparé n'est pas démontré. Ne pas lancer des tours ou objectifs pour précharger. À tester avant intégration au mode d'emploi.

## Pièces privées non distribuées

Pas de backup, SQLite utilisateur, fichiers d'authentification, rollouts, screenshots bruts (voir les 34 captures anonymisees dans screenshots/) ou plan de reprise exécutable. Les extraits par liste blanche conservent les résultats et étapes sans divulguer noms, chemins ou contenu. Aucun fichier réel n'est remplacé par un jeu de données synthétique présenté comme preuve réelle.
