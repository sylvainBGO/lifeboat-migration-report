# Mesurer Lifeboat sur votre PC

1. Extrayez **tout le ZIP** dans un dossier local. Gardez ses trois exécutables ensemble.
2. Ouvrez **Lancer-Benchmark.cmd**, puis choisissez **Rapide** ou **Approfondi**.
3. Choisissez le dossier des résultats et cliquez sur **Démarrer**.
4. Transmettez les deux fichiers `benchmark-lifeboat-*.json` et `.txt` créés dans ce dossier.

Le mode rapide utilise de petits jeux avec un passage. Le mode approfondi utilise
des jeux plus importants et **2 à 5 répétitions**, 3 par défaut. La durée dépend du
PC et du disque : aucun délai de quelques minutes n’est garanti.

Les données sont synthétiques et reproductibles. Le programme ne demande jamais
votre sauvegarde ni le dossier de votre profil. Il vérifie l’espace avant de
générer ses données : **1,5 Go** en mode rapide, **3 Go** en mode approfondi.
Seul le dossier temporaire qu’il a créé est nettoyé. Vos rapports sont conservés.
Pour la comparaison complète, fermez les applications **Codex** et **ChatGPT**
avant de démarrer. La garde de production est vérifiée avant de générer les
données et reste active ; le site ChatGPT ouvert dans le navigateur n’est pas
une application Windows à fermer.

## Ce qui est comparé

**Restauration complète** compare l’amont v3.4.11 avec les sources finales de la
version communautaire incluses dans ce paquet, dans deux processus distincts.
Les deux variantes valident la source, préparent la restauration et vérifient
le résultat. Le temps de la version finale comprend son plan et ses journaux
durables de reprise. Les identités des sources et exécutables figurent dans
`BENCHMARK-BUILD.json` et dans le rapport. Un composant manquant ou modifié fait
échouer la comparaison ; le programme ne bascule pas sur une ancienne variante.

La case **Comparer les archives** ajoute le format de production
`archive-blocks-v1` de la version finale. Pour chaque variante et répétition, un
backup distinct est construit depuis le même jeu source. Le rapport donne
**création du backup**, **restauration avec validation** et **leur total**. Le
coût de préparation des archives n’est donc pas caché. Les registres de chaque
essai sont isolés. Des empreintes vérifient hors chronomètre que le contenu et
l’ensemble des fichiers source et backup n’ont pas changé ; elles ne prouvent
pas l’invariance de toutes les métadonnées et peuvent réchauffer le cache.

**Copies et archives** est un ensemble de microtests. Le ZIP y est créé à partir
des seules données synthétiques, et sa préparation est mesurée séparément.
Ces microtests n’ont pas tous les mêmes garanties de métadonnées. Un ZIP plus
rapide dans ce tableau ne prouve pas qu’une restauration complète est plus rapide.

Les répétitions et leur ordre sont conservés. Le premier passage est distingué
des suivants, mais **le cache Windows n’est pas vidé** : « premier passage » ne
signifie pas « cache froid ». Les variantes complètes alternent leur ordre entre
les répétitions. Les temps très courts sont sensibles au bruit.
Les paires dont les états Defender connus diffèrent, ou dont l’état change
pendant un essai, sont exclues des gains. Un état incomplet est signalé comme
condition non vérifiée. La provenance d’un checkout local non vérifié n’est pas
présentée comme celle du commit officiel épinglé.

## Arrêter

**Arrêter après l’essai en cours** laisse cet essai se terminer et conserve les
résultats déjà obtenus. **Interrompre** demande l’arrêt au prochain point sûr ; un
worker de restauration synthétique est interrompu et ses données temporaires
sont ensuite nettoyées. Les microtests en cours peuvent finir leur essai avant
de prendre en compte cette demande. En ligne de commande, `Ctrl+C` conserve aussi
les rapports partiels.

Un rapport partiel n’annonce pas une campagne réussie. Les gains sont calculés
uniquement sur des paires original/final complètes et valides. Une extinction
brutale peut laisser un dossier temporaire `lb-benchmark-*` ; aucune reprise de
performance à partir de ce dossier n’est nécessaire.

## Microsoft Defender

L’état est affiché et relevé dans le rapport. Le bouton **Désactiver
temporairement…** présente une explication, puis demande la validation
administrateur Windows. Seule cette action explicite demande une désactivation.
Le programme vérifie l’état réel après la demande.

Si la demande est refusée ou bloquée par la protection des paramètres ou une
politique, utilisez **Ouvrir Sécurité Windows** et procédez manuellement si vos
droits le permettent. Une politique d’entreprise peut nécessiter l’administrateur.
L’acceptation de l’UAC n’est pas présentée comme une preuve de désactivation.

Le programme **ne réactive jamais automatiquement** Defender et ne le désactive
pas silencieusement si Windows l’a réactivé. Un changement d’état est signalé.
**Pensez à réactiver manuellement la protection en temps réel après les mesures,
y compris après annulation ou erreur.**

Les tests automatiques ne modifient aucun réglage Defender ; les contrats de
désactivation sont vérifiés avec un faux composant.

## Ligne de commande et reproductibilité

Sur Windows, les mêmes mesures peuvent être lancées sans fenêtre :

```powershell
$p = Start-Process .\Lifeboat-Benchmark.exe -ArgumentList '--headless --mode thorough --repeats 3 --focus restore --include-archives --directory results' -Wait -PassThru
$p.ExitCode
```

Codes : `0` campagne terminée et valide, `2` arrêt ou interruption, `1` échec.
Les résultats restent dans `results`, y compris lorsque l’exécutable sans console
n’affiche pas de texte dans le terminal.

Pour développer et exécuter depuis les sources sur Windows :

```powershell
python performance/benchmarks/benchmark.py --headless --mode thorough --repeats 3 --baseline-source baseline/src --final-source final/src --focus restore
```

Les scénarios versionnés sont décrits dans `scenarios.json`. Les essais ne
prédisent pas la durée d’une sauvegarde de 88 Gio ou de plusieurs millions de
fichiers. Une amélioration observée peut dépendre du stockage, du cache et de
Defender ; les rapports permettent de comparer ces conditions explicitement.
