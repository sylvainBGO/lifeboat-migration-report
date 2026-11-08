"""Durable, shareable benchmark reports (JSON and readable text).

Reports describe synthetic trials only. A partial run never claims a passing
campaign or compares an unmatched baseline with a completed candidate.
"""
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import tempfile


PROTOCOL_VERSION = '2026-11-production-path-2'
CACHE_NOTE = (
    'Le cache Windows n’est pas vidé. « Premier passage » désigne la première '
    'observation de la variante, pas une mesure garantie à cache froid. '
    'Les variantes alternent leur ordre entre les répétitions.'
)
DEFENDER_REMINDER = (
    'Si vous avez désactivé la protection en temps réel de Microsoft Defender, '
    'pensez à la réactiver manuellement. Ce programme ne la réactive jamais.'
)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _atomic_text(path, text):
    path = Path(path)
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name + '-', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _defender_text(state):
    if not state or not (state.get('available') or state.get('status') == 'ok'):
        return 'état indisponible'
    enabled = state.get('RealTimeProtectionEnabled')
    return 'protection active' if enabled is True else 'protection désactivée' if enabled is False else 'état inconnu'


def _condition(trial):
    before = (trial.get('defender_before') or {}).get('RealTimeProtectionEnabled')
    after = (trial.get('defender_after') or {}).get('RealTimeProtectionEnabled')
    if isinstance(before, bool) and isinstance(after, bool):
        return ('enabled' if before else 'disabled') if before == after else 'changed'
    return 'unknown'


def paired_comparisons(trials, reference='baseline', candidate='final'):
    """Use complete, valid pairs from the same profile/repetition only."""
    pairs = defaultdict(dict)
    for trial in trials:
        if trial.get('kind') != 'restore' or not trial.get('valid'):
            continue
        pairs[(trial.get('profile'), trial.get('repeat'))][trial.get('variant')] = trial
    profiles = defaultdict(lambda: {'baseline': [], 'final': [], 'paired_repeats': []})
    for (profile, repeat), pair in sorted(pairs.items()):
        if reference not in pair or candidate not in pair:
            continue
        if not pair[candidate].get('durable_checkpoints'):
            continue
        if pair[reference].get('protocol_version') != pair[candidate].get('protocol_version'):
            continue
        conditions = [_condition(pair[reference]), _condition(pair[candidate])]
        known_states = {(pair[variant].get(boundary) or {}).get('RealTimeProtectionEnabled')
                        for variant in (reference, candidate)
                        for boundary in ('defender_before', 'defender_after')
                        if isinstance((pair[variant].get(boundary) or {}).get('RealTimeProtectionEnabled'), bool)}
        if 'changed' in conditions or known_states == {True, False}:
            continue
        item = profiles[profile]
        item['baseline'].append(pair[reference]['seconds'])
        item['final'].append(pair[candidate]['seconds'])
        item['paired_repeats'].append(repeat)
        item.setdefault('conditions', []).append(conditions)
        if all(isinstance(pair[v].get('backup_seconds'), (int, float)) for v in (reference, candidate)):
            item.setdefault('baseline_backup', []).append(pair[reference]['backup_seconds'])
            item.setdefault('final_backup', []).append(pair[candidate]['backup_seconds'])
            item.setdefault('baseline_total', []).append(pair[reference]['total_seconds'])
            item.setdefault('final_total', []).append(pair[candidate]['total_seconds'])
    result = {}
    for profile, item in profiles.items():
        baseline = statistics.median(item['baseline'])
        final = statistics.median(item['final'])
        result[profile] = dict(
            pairs=len(item['paired_repeats']),
            paired_repeats=item['paired_repeats'],
            baseline_median_seconds=baseline,
            final_median_seconds=final,
            reduction_percent=(100 * (baseline - final) / baseline) if baseline > 0 else None,
            reference=reference, candidate=candidate,
            defender_conditions_known=all('unknown' not in c for c in item['conditions']),
        )
        if item.get('baseline_total'):
            reference_total = statistics.median(item['baseline_total'])
            candidate_total = statistics.median(item['final_total'])
            result[profile].update(
                baseline_backup_median_seconds=statistics.median(item['baseline_backup']),
                final_backup_median_seconds=statistics.median(item['final_backup']),
                baseline_total_median_seconds=reference_total,
                final_total_median_seconds=candidate_total,
                total_reduction_percent=100 * (reference_total - candidate_total) / reference_total,
            )
    return result


def readable(report):
    labels = {'running': 'EN COURS', 'complete': 'TERMINÉ', 'stopped': 'ARRÊT APRÈS ESSAI',
              'cancelled': 'INTERROMPU', 'failed': 'ÉCHEC'}
    trials = report.get('trials', [])
    comparisons = paired_comparisons(trials)
    archive_comparisons = paired_comparisons(trials, 'final', 'final_archive')
    lines = [
        'LIFEBOAT — RAPPORT DE MESURES SYNTHÉTIQUES',
        '',
        'État : ' + labels.get(report.get('status'), str(report.get('status', 'inconnu'))),
        'Début : ' + report.get('started_at', 'inconnu'),
        'Fin : ' + report.get('finished_at', 'pas encore terminée'),
        'Mode : ' + report.get('mode', 'inconnu'),
        'Protocole : ' + report.get('protocol_version', 'antérieur / non renseigné'),
        'Répétitions demandées : ' + str(report.get('repeats', '?')),
        f"Essais terminés : {len(trials)}/{report.get('planned_trials', '?')}",
        'Campagne validée : ' + ('oui' if report.get('passed') is True else 'non / incomplète'),
        'Archives de production : ' + ('incluses' if report.get('include_archives') else 'non demandées'),
        '',
        'MÉTHODE',
        CACHE_NOTE,
        'La restauration inclut le plan comparatif, ses décisions limitées aux fixtures,',
        'la validation de la source, la préparation, la copie et la vérification finale.',
        'Les contrôles de fermeture de Codex/ChatGPT du parcours GUI restent actifs ;',
        'la version finale inclut aussi son plan et ses journaux durables de reprise.',
        'Le backup, avec son contrôle de fermeture, est mesuré séparément et ajouté',
        'au total. Génération du jeu, empreintes de contrôle et attente humaine exclues.',
        'Le protocole précédent omettait le plan comparatif et des gardes communes :',
        'ses temps ne sont pas interchangeables avec ceux de ce protocole.',
        'Les workers baseline/final sont des processus séparés. Aucun contrôle',
        'd’intégrité n’est désactivé. Aucune donnée personnelle n’est utilisée.',
        '',
        'COMPARAISONS COMPLÈTES',
    ]
    if not comparisons:
        lines.append('Aucune paire complète et valide : aucun gain ne peut être conclu.')
    for profile, item in comparisons.items():
        lines.append(
            f"{profile}: {item['pairs']} paire(s), médiane original "
            f"{item['baseline_median_seconds']:.3f} s → version finale "
            f"{item['final_median_seconds']:.3f} s ; "
            f"réduction {item['reduction_percent']:+.1f} %."
        )
        if item.get('baseline_total_median_seconds') is not None:
            lines.append(f"  Sauvegarde : {item['baseline_backup_median_seconds']:.3f} → {item['final_backup_median_seconds']:.3f} s ; "
                         f"total sauvegarde + restauration : {item['baseline_total_median_seconds']:.3f} → "
                         f"{item['final_total_median_seconds']:.3f} s ({item['total_reduction_percent']:+.1f} %).")
        if not item['defender_conditions_known']:
            lines.append('  État Defender incomplet : conditions de protection non vérifiées pour cette comparaison.')
    if report.get('include_archives'):
        lines += ['', 'ARCHIVES DE PRODUCTION — VERSION FINALE FICHIERS / ARCHIVES']
        if not archive_comparisons:
            lines.append('Aucune paire valide dans des conditions Defender comparables.')
        for profile, item in archive_comparisons.items():
            lines.append(f"{profile}: {item['pairs']} paire(s), restauration fichiers {item['baseline_median_seconds']:.3f} s "
                         f"→ archives {item['final_median_seconds']:.3f} s ({item['reduction_percent']:+.1f} %).")
            if item.get('baseline_total_median_seconds') is not None:
                lines.append(f"  Création du backup : {item['baseline_backup_median_seconds']:.3f} → {item['final_backup_median_seconds']:.3f} s ; "
                             f"total : {item['baseline_total_median_seconds']:.3f} → {item['final_total_median_seconds']:.3f} s "
                             f"({item['total_reduction_percent']:+.1f} %).")
            if not item['defender_conditions_known']:
                lines.append('  État Defender incomplet : conditions non vérifiées.')
    if any(_condition(t) == 'changed' for t in trials) or report.get('defender_changed'):
        lines.append('Les paires dont les états Defender connus diffèrent ou changent pendant un essai sont exclues des gains.')
    lines += ['', 'DÉTAIL DES ESSAIS (ordre réel)']
    for position, trial in enumerate(trials, 1):
        name = '/'.join(str(trial.get(k, '?')) for k in ('kind', 'profile', 'variant'))
        elapsed = trial.get('seconds')
        duration = f'{elapsed:.3f} s' if isinstance(elapsed, (float, int)) else 'temps indisponible'
        verdict = 'OK' if trial.get('valid') is True else 'ÉCHEC'
        passage = 'premier passage' if trial.get('repeat', 0) == 0 else 'passage suivant'
        lines.append(f"{position:02d}. {name}, répétition {trial.get('repeat', 0) + 1}, "
                     f'{passage} : {duration}, {verdict}.')
        if trial.get('backup_seconds') is not None:
            lines.append(f"    Backup {trial['backup_seconds']:.3f} s + restauration {trial['seconds']:.3f} s "
                         f"= {trial['total_seconds']:.3f} s ; source et backup inchangés vérifiés hors chrono.")
        if all(isinstance(trial.get(key), (float, int)) for key in ('plan_seconds', 'prepare_seconds', 'restore_seconds')):
            lines.append(f"    Détail restauration : plan {trial['plan_seconds']:.3f} s ; "
                         f"préparation {trial['prepare_seconds']:.3f} s ; exécution et vérification {trial['restore_seconds']:.3f} s.")
    if report.get('archive_setup'):
        lines += ['', 'PRÉPARATION DES ARCHIVES (hors temps d’extraction)']
        for item in report['archive_setup']:
            lines.append(f"{item['profile']}: création ZIP {item['seconds']:.3f} s, "
                         f"{item.get('archive_bytes', '?')} octets.")
    lines += ['', 'MICROTESTS DE COPIE ET ARCHIVES']
    lines.append('Ces microtests isolés n’ont pas tous les mêmes garanties de métadonnées.')
    lines.append('Ils ne remplacent pas la comparaison complète de restauration ci-dessus.')
    lines += ['', 'MICROSOFT DEFENDER',
              'Au début : ' + _defender_text(report.get('defender_start')),
              'À la fin : ' + _defender_text(report.get('defender_end')),
              'L’état est observé aux limites des essais, sans changement automatique.']
    if report.get('defender_changed'):
        lines.append('ATTENTION : l’état observé a changé ; ces conditions sont à comparer séparément.')
    lines += ['', 'LIMITES']
    lines.extend('- ' + str(value) for value in report.get('limitations', []))
    if report.get('errors'):
        lines += ['', 'ERREURS']
        lines.extend('- ' + str(value) for value in report['errors'])
    lines += ['', DEFENDER_REMINDER, '', 'Les deux fichiers JSON et TXT peuvent être transmis ensemble.']
    return '\n'.join(lines) + '\n'


def save_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    report['comparisons'] = paired_comparisons(report.get('trials', []))
    report['archive_comparisons'] = paired_comparisons(report.get('trials', []), 'final', 'final_archive')
    _atomic_text(path, json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    _atomic_text(path.with_suffix('.txt'), readable(report))


def defender_state():
    """Read through the production module; never request a settings change."""
    try:
        from codex_transfer import defender_control
        value = defender_control.status()
        # Keep the report shareable: do not serialize arbitrary PowerShell output.
        return {key: value[key] for key in
                ('available', 'RealTimeProtectionEnabled', 'IsTamperProtected') if key in value}
    except (ImportError, OSError, ValueError, RuntimeError, TimeoutError):
        return {'available': False}
    except Exception as exc:
        return {'available': False, 'error_type': type(exc).__name__}
