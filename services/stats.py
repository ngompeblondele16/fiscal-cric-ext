"""Service centralisé de calcul des statistiques fiscales."""
import json
import unicodedata
from datetime import datetime

from sqlalchemy import func, or_, case

from models import Contribuable, ImportHistory, TreatmentSnapshot
from cdi_config import CFLP_GROUPS, get_all_cflp_labels, normalize_cdi
from fiscal_constants import (
    MONTANT_NEANT_MAX,
    ETAT_DEFAILLANT,
    ETAT_NEANT,
    ETAT_RELICATAIRE,
    ETAT_DECLARANT,
    ETAT_LABELS,
)
from services.consolidation import load_monthly_recu_dict, ensure_monthly_recu_cached

# États « présents dans le consolidé » (ont déclaré)
_ETATS_DECLARATION = (ETAT_NEANT, ETAT_RELICATAIRE, ETAT_DECLARANT)
# États avec paiement enregistré (néant ou significatif)
_ETATS_PAYE = (ETAT_NEANT, ETAT_DECLARANT)

_MONTH_LABELS = [
    'Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Jun',
    'Jul', 'Aoû', 'Sep', 'Oct', 'Nov', 'Déc',
]

_RECETTES_COLORS = [
    '#e85d04', '#1e40af', '#059669', '#7c3aed', '#dc2626', '#0891b2',
]

_DEFAULT_COMPARE_YEARS = (2026, 2025)

_SOUS_SECTEUR_DISPLAY_ORDER = [
    'Agriculture',
    'Sylviculture',
    'Industrie Extractive',
    'Industries Agroalimentaires',
    'Industries Manufasturières',
    'Eau et Electricité',
    'Construction',
    'Commerce Général',
    'Prestation de Service',
    'Vente de Boisson',
    'Restaurant et Hébergement',
    'Transport et communication',
    'Banques et Assurance',
    'Services marchands',
    'Administration Publique',
    'Education',
    'Service non marchands',
    'Particulier',
    '#N/A',
]
_SOUS_SECTEUR_ORDER_INDEX = {
    ''.join(
        c for c in unicodedata.normalize('NFKD', label.lower().strip())
        if not unicodedata.combining(c)
    ): idx
    for idx, label in enumerate(_SOUS_SECTEUR_DISPLAY_ORDER)
}
_SOUS_SECTEUR_ORDER_ALIASES = {
    'industries manufacturieres': 'industries manufasturieres',
    'services non marchands': 'service non marchands',
    'service marchands': 'services marchands',
}


# ---------------------------------------------------------------------------
# Helpers — agrégations SQL
# ---------------------------------------------------------------------------

def _count_by_etat(db, etat):
    return db.query(Contribuable).filter(Contribuable.etat == etat).count()


def _sum_montant_declare_by_etat(db, etat):
    val = db.query(func.coalesce(func.sum(Contribuable.montant_declare), 0)).filter(
        Contribuable.etat == etat
    ).scalar()
    return float(val or 0)


def _sum_montant_paye_by_etat(db, etat):
    val = db.query(func.coalesce(func.sum(Contribuable.montant_paye), 0)).filter(
        Contribuable.etat == etat
    ).scalar()
    return float(val or 0)


def _sum_montant_declare_for_etats(db, etats):
    val = db.query(func.coalesce(func.sum(Contribuable.montant_declare), 0)).filter(
        Contribuable.etat.in_(list(etats))
    ).scalar()
    return float(val or 0)


def _sum_montant_paye_for_etats(db, etats):
    val = db.query(func.coalesce(func.sum(Contribuable.montant_paye), 0)).filter(
        Contribuable.etat.in_(list(etats))
    ).scalar()
    return float(val or 0)


def _sum_montant_attendu(db):
    val = db.query(func.coalesce(func.sum(Contribuable.montant_attendu), 0)).scalar()
    return float(val or 0)


def _pct(part, total, digits=1):
    if not total:
        return 0.0
    return round(part / total * 100, digits)


def _safe_cflp_label(cdi):
    if not cdi:
        return 'N/A'
    return normalize_cdi(cdi) or cdi


def _normalize_order_key(value):
    raw = (value or '').strip().lower()
    norm = ''.join(
        c for c in unicodedata.normalize('NFKD', raw)
        if not unicodedata.combining(c)
    )
    return _SOUS_SECTEUR_ORDER_ALIASES.get(norm, norm)


def _format_fcfa_full(amount):
    """Montant FCFA complet (pas d'abréviation M/Md)."""
    try:
        return f"{int(round(float(amount or 0))):,}".replace(',', ' ')
    except (TypeError, ValueError):
        return '0'


def _nice_y_ticks(max_value, count=5):
    """Graduations Y pour le graphique recettes — valeurs entières FCFA."""
    if max_value <= 0:
        return [0]
    step = max(1, int(max_value / count))
    magnitude = 10 ** max(0, len(str(step)) - 2)
    step = max(magnitude, (step + magnitude - 1) // magnitude * magnitude)
    ticks = []
    v = 0
    while v <= max_value * 1.05:
        ticks.append(v)
        v += step
    if ticks[-1] < max_value:
        ticks.append(int(max_value))
    return ticks


def _aggregate_dimension(db, group_col, label_key='label'):
    """
    Agrège contribuables par dimension (secteur ou CFLP).
    Retourne un dict label -> stats.
    """
    rows = db.query(
        group_col,
        func.count(Contribuable.id),
        func.sum(case((Contribuable.etat == ETAT_DEFAILLANT, 1), else_=0)),
        func.sum(case((Contribuable.etat == ETAT_NEANT, 1), else_=0)),
        func.sum(case((Contribuable.etat == ETAT_RELICATAIRE, 1), else_=0)),
        func.sum(case((Contribuable.etat == ETAT_DECLARANT, 1), else_=0)),
        func.coalesce(func.sum(Contribuable.montant_declare), 0),
        func.coalesce(func.sum(
            case((Contribuable.etat.in_(_ETATS_PAYE), Contribuable.montant_paye), else_=0)
        ), 0),
    ).group_by(group_col).all()

    out = {}
    for r in rows:
        raw_label = r[0] or '#N/A'
        label = _normalize_secteur_cime_label(raw_label) if group_col is Contribuable.secteur else _safe_cflp_label(raw_label)
        total = int(r[1] or 0)
        defaillants = int(r[2] or 0)
        neants = int(r[3] or 0)
        relicataires = int(r[4] or 0)
        declarants = int(r[5] or 0)
        declares = neants + relicataires + declarants
        montant_declare = float(r[6] or 0)
        montant_recu = float(r[7] or 0)
        out[label] = {
            label_key: label,
            'label': label,
            'total': total,
            'contribuables': total,
            'taille_fichier': total,
            'defaillants': defaillants,
            'neants': neants,
            'relicataires': relicataires,
            'declarants': declarants,
            'declarants_total': neants + declarants,
            'declarations': declares,
            'non_contributeur': defaillants + neants,
            'taux_declaration': _pct(declares, total),
            'taux_non_contributeur': _pct(defaillants + neants, total),
            'montant_declare': montant_declare,
            'montant_recu': montant_recu,
            'ecart': montant_declare - montant_recu,
            'taux_encaissement': _pct(montant_recu, montant_declare),
        }
    return out


def _empty_dimension_bucket(label):
    """Structure complète pour une ligne vide (secteur / CFLP sans données)."""
    return {
        'label': label,
        'total': 0,
        'contribuables': 0,
        'taille_fichier': 0,
        'defaillants': 0,
        'neants': 0,
        'relicataires': 0,
        'declarants': 0,
        'declarants_total': 0,
        'declarations': 0,
        'non_contributeur': 0,
        'taux_declaration': 0.0,
        'taux_non_contributeur': 0.0,
        'montant_declare': 0.0,
        'montant_recu': 0.0,
        'ecart': 0.0,
        'taux_encaissement': 0.0,
    }


def _total_row_from_buckets(buckets, label='Total général'):
    if not buckets:
        return None
    total = sum(b.get('total', b.get('contribuables', 0)) for b in buckets)
    taille = sum(b.get('taille_fichier', 0) for b in buckets) or total
    defaillants = sum(b.get('defaillants', 0) for b in buckets)
    neants = sum(b.get('neants', 0) for b in buckets)
    relicataires = sum(b.get('relicataires', 0) for b in buckets)
    declarants = sum(b.get('declarants', 0) for b in buckets)
    montant_declare = sum(b.get('montant_declare', 0) for b in buckets)
    montant_recu = sum(b.get('montant_recu', 0) for b in buckets)
    return {
        'label': label,
        'total': total,
        'contribuables': total,
        'taille_fichier': taille,
        'defaillants': defaillants,
        'neants': neants,
        'relicataires': relicataires,
        'declarants': declarants,
        'declarants_total': neants + declarants,
        'declarations': declarants,
        'non_contributeur': defaillants + neants,
        'taux_declaration': _pct(declarants, taille),
        'taux_non_contributeur': _pct(defaillants + neants, taille),
        'montant_declare': montant_declare,
        'montant_recu': montant_recu,
        'ecart': montant_declare - montant_recu,
        'taux_encaissement': _pct(montant_recu, montant_declare),
    }


# ---------------------------------------------------------------------------
# Statistiques globales — logique RECHERCHEV (identique TCD secteur / import)
# ---------------------------------------------------------------------------

def _sector_tcd_etat(c):
    """TCD : #N/A · 0–10 · >10 (déclarants + relicataires = montant déclaré significatif)."""
    if c.etat == ETAT_DEFAILLANT or c.etat is None:
        return ETAT_DEFAILLANT
    md = float(c.montant_declare or 0)
    if md <= MONTANT_NEANT_MAX:
        return ETAT_NEANT
    return ETAT_DECLARANT


def _etat_bucket(c):
    """État stocké en base (0–3) — utilisé pour listes et KPI détaillés."""
    etat = c.etat if c.etat is not None else ETAT_DEFAILLANT
    if etat in (ETAT_DEFAILLANT, ETAT_NEANT, ETAT_RELICATAIRE, ETAT_DECLARANT):
        return etat
    return ETAT_DEFAILLANT


def _contribuables_by_sector_tcd(db, target_etat):
    """Filtre TCD (montant déclaré) — relicataires + déclarants = montant > 10."""
    return [
        c for c in db.query(Contribuable).order_by(Contribuable.raison).all()
        if _sector_tcd_etat(c) == target_etat
    ]


def _contribuables_by_etat(db, target_etat):
    """Filtre par état stocké (0–3) — listes menu."""
    return [
        c for c in db.query(Contribuable).order_by(Contribuable.raison).all()
        if _etat_bucket(c) == target_etat
    ]


def get_global_stats(db):
    """Statistiques globales — alignées import RECHERCHEV (états 0–3)."""
    defaillants = neants = relicataires = declarants = 0
    sum_declare = 0.0
    sum_paye = 0.0

    for c in db.query(Contribuable).all():
        etat = _etat_bucket(c)
        if etat == ETAT_DEFAILLANT:
            defaillants += 1
        elif etat == ETAT_NEANT:
            neants += 1
        elif etat == ETAT_RELICATAIRE:
            relicataires += 1
        else:
            declarants += 1
        sum_declare += float(c.montant_declare or 0)
        if c.montant_paye is not None:
            sum_paye += float(c.montant_paye or 0)

    total = defaillants + neants + relicataires + declarants
    declares_significatifs = relicataires + declarants
    taux_declaration = _pct(declares_significatifs, total)
    taux_defaillant = _pct(defaillants, total)
    taux_neant = _pct(neants, total)
    taux_relicataire = _pct(relicataires, total)
    taux_declarant = _pct(declarants, total)
    pct_neants_in_declarants = _pct(neants, neants + declares_significatifs) if declares_significatifs else 0.0

    return {
        'total': total,
        'defaillants': defaillants,
        'neants': neants,
        'relicataires': relicataires,
        'declarants': declarants,
        'declarants_total': declares_significatifs,
        'pct_neants_in_declarants': pct_neants_in_declarants,
        'declared': declares_significatifs,
        'non_declared': defaillants,
        'paid': declarants,
        'taux_declaration': taux_declaration,
        'taux_defaillant': taux_defaillant,
        'taux_neant': taux_neant,
        'taux_relicataire': taux_relicataire,
        'taux_declarant': taux_declarant,
        'etat_0': defaillants,
        'etat_1': neants,
        'etat_2': relicataires,
        'etat_3': declarants,
        'sum_montant': _sum_montant_attendu(db),
        'sum_declare': sum_declare,
        'sum_declare_attendu': sum_declare,
        'sum_paye': sum_paye,
        'sum_montant_recu': sum_paye,
        'neant_max': MONTANT_NEANT_MAX,
    }


# ---------------------------------------------------------------------------
# Agrégations par dimension
# ---------------------------------------------------------------------------

def get_by_cdi(db):
    """Statistiques par CFLP — taux déclaration = montant > 10 / total (RECHERCHEV)."""
    by_name = {}
    max_decl = 1
    for c in db.query(Contribuable).all():
        cdi = _safe_cflp_label(c.cdi)
        if cdi == 'N/A':
            continue
        if cdi not in by_name:
            by_name[cdi] = {
                'cdi': cdi,
                'declares': 0,
                'declarants': 0,
                'neants': 0,
                'relicataires': 0,
                'non_declares': 0,
                'defaillants': 0,
                'montant': 0.0,
                'total': 0,
                'progress': 0,
            }
        row = by_name[cdi]
        row['total'] += 1
        row['montant'] += float(c.montant_declare or 0)
        cat = _sector_tcd_etat(c)
        if cat == ETAT_DEFAILLANT:
            row['defaillants'] += 1
            row['non_declares'] += 1
        elif cat == ETAT_NEANT:
            row['neants'] += 1
        else:
            row['declarants'] += 1
        row['declares'] = row['declarants']
        max_decl = max(max_decl, row['declarants'])

    for cdi in get_all_cflp_labels():
        if cdi not in by_name:
            by_name[cdi] = {
                'cdi': cdi,
                'declares': 0,
                'declarants': 0,
                'neants': 0,
                'relicataires': 0,
                'non_declares': 0,
                'defaillants': 0,
                'montant': 0.0,
                'total': 0,
                'progress': 0,
            }

    result = list(by_name.values())
    for row in result:
        row['progress'] = min(100, int(row['declarants'] / row['total'] * 100)) if row['total'] else 0
    result.sort(key=lambda x: x['montant'], reverse=True)
    return result


def get_by_secteur(db):
    rows = db.query(
        Contribuable.secteur,
        func.count(Contribuable.id),
        func.coalesce(func.sum(Contribuable.montant_declare), 0),
    ).group_by(Contribuable.secteur).all()
    result = [{'secteur': r[0] or 'N/A', 'count': r[1], 'montant': float(r[2] or 0)} for r in rows]
    result.sort(key=lambda x: x['montant'], reverse=True)
    return result


def get_by_etat(db):
    stats = get_global_stats(db)
    return [
        {
            'label': 'Défaillants — #N/A RECHERCHEV (absents du consolidé)',
            'etat': ETAT_DEFAILLANT,
            'count': stats['defaillants'],
            'montant': _sum_montant_declare_by_etat(db, ETAT_DEFAILLANT),
            'value': round(stats['taux_defaillant']),
        },
        {
            'label': f'Néants — montant déclaré 0 à {int(MONTANT_NEANT_MAX)} FCFA',
            'etat': ETAT_NEANT,
            'count': stats['neants'],
            'montant': _sum_montant_declare_by_etat(db, ETAT_NEANT),
            'value': round(stats['taux_neant']),
        },
        {
            'label': f'Déclarants — montant déclaré > {int(MONTANT_NEANT_MAX)} FCFA',
            'etat': ETAT_DECLARANT,
            'count': stats['declarants'],
            'montant': _sum_montant_declare_for_etats(db, (ETAT_DECLARANT, ETAT_RELICATAIRE)),
            'value': round(stats['taux_declaration']),
        },
    ]


# ---------------------------------------------------------------------------
# Graphiques dashboard
# ---------------------------------------------------------------------------

def get_cflp_declaration_rates(db, limit=None):
    """Taux de déclaration par CFLP : présents dans le consolidé / total."""
    by_cdi = get_by_cdi(db)
    result = []
    for r in by_cdi:
        total = int(r['total'] or 0)
        declares = int(r['declares'] or 0)
        pct = _pct(declares, total)
        result.append({
            'label': r['cdi'],
            'cdi': r['cdi'],
            'pct': pct,
            'total': total,
            'declares': declares,
            'declarants': int(r['declarants'] or 0),
            'neants': int(r['neants'] or 0),
            'relicataires': int(r['relicataires'] or 0),
            'defaillants': int(r['defaillants'] or 0),
        })
    result.sort(key=lambda x: (x['total'] > 0, x['pct']), reverse=True)
    if limit:
        active = [x for x in result if x['total'] > 0]
        result = active[:limit] if active else result[:limit]
    return result


def get_cdi_chart_data(db, limit=5):
    rates = get_cflp_declaration_rates(db, limit=limit)
    return [
        {'label': r['label'], 'pct': r['pct'], 'total': r['total'], 'declares': r['declares']}
        for r in rates
    ]


def get_secteur_chart_data(db, limit=6):
    by_sect = get_by_secteur(db)[:limit]
    if not by_sect:
        return []
    max_montant = max(r['montant'] for r in by_sect) or 1
    return [
        {
            'name': r['secteur'],
            'height': max(20, int(r['montant'] / max_montant * 160)),
        }
        for r in by_sect
    ]


def get_evolution_data(db):
    """Évolution du taux de déclaration sur les derniers traitements."""
    snapshots = db.query(TreatmentSnapshot).order_by(TreatmentSnapshot.date_run.asc()).limit(12).all()
    if snapshots:
        return {
            'labels': [s.date_run.strftime('%d/%m') if s.date_run else '' for s in snapshots],
            'values': [float(s.taux_declaration or 0) for s in snapshots],
            'metric': 'taux_declaration',
        }
    imports = db.query(ImportHistory).order_by(ImportHistory.date_import.asc()).limit(12).all()
    if not imports:
        return {'labels': [], 'values': [], 'metric': 'taux_declaration'}
    labels = []
    values = []
    cumulative = 0
    for imp in imports:
        labels.append(imp.date_import.strftime('%d/%m') if imp.date_import else '')
        cumulative += imp.nb_lignes or 0
        values.append(cumulative)
    return {'labels': labels, 'values': values, 'metric': 'lignes_importees'}


def _month_amounts_for_year(monthly_dict, year):
    """Montants reçus par numéro de mois (1–12) pour une année."""
    year_key = str(int(year))
    months_data = monthly_dict.get(year_key, {}) if monthly_dict else {}
    by_month = {}
    for key, raw in (months_data or {}).items():
        try:
            month = int(key)
            amount = float(raw or 0)
        except (TypeError, ValueError):
            continue
        if 1 <= month <= 12 and amount > 0:
            by_month[month] = by_month.get(month, 0.0) + amount
    return by_month


def _months_for_recettes_chart(monthly_dict, years):
    """
    Janvier → dernier mois avec recettes datées sur l'année de référence (la plus récente).
    Ex. fichiers jan–juin 2026 → axe jan–juin uniquement (pas juillet–décembre à 0 ni étiré par 2025).
    """
    if not years:
        return []
    ref_year = max(int(y) for y in years)
    by_month = _month_amounts_for_year(monthly_dict, ref_year)
    if by_month:
        return list(range(1, max(by_month.keys()) + 1))
    for year in sorted({int(y) for y in years}, reverse=True):
        by_month = _month_amounts_for_year(monthly_dict, year)
        if by_month:
            return list(range(1, max(by_month.keys()) + 1))
    return []


def _monthly_values_for_year(monthly_dict, year, months):
    by_month = _month_amounts_for_year(monthly_dict, year)
    return [by_month.get(m, 0.0) for m in months]


def _compare_years_for_recettes(available_years, preferred=_DEFAULT_COMPARE_YEARS):
    """Sélectionne 1 ou 2 années pour la comparaison (2026 vs 2025 par défaut)."""
    years_sorted = sorted({int(y) for y in available_years}, reverse=True)
    if not years_sorted:
        return []
    chosen = []
    for y in preferred:
        if y in years_sorted and y not in chosen:
            chosen.append(y)
    for y in years_sorted:
        if y not in chosen:
            chosen.append(y)
        if len(chosen) >= 2:
            break
    return chosen[:2] if len(chosen) >= 2 else chosen[:1]


def _build_recettes_chart_payload(monthly_dict, compare_years=None):
    """
    Construit le payload SVG pour le dashboard.
    Montants reçus (TCD date_creation) — axe Y en FCFA complets.
    """
    if not monthly_dict:
        return {
            'labels': _MONTH_LABELS,
            'years': [],
            'series': [],
            'y_ticks': [0],
            'y_tick_labels': ['0'],
            'max_value': 0,
            'mode': 'empty',
            'subtitle': 'Importez des fichiers sectoriels avec date de création et montant reçu',
        }

    available = [int(y) for y in monthly_dict.keys() if str(y).isdigit()]
    years = _compare_years_for_recettes(available, compare_years or _DEFAULT_COMPARE_YEARS)
    if not years:
        return {
            'labels': _MONTH_LABELS,
            'years': [],
            'series': [],
            'y_ticks': [0],
            'y_tick_labels': ['0'],
            'max_value': 0,
            'mode': 'empty',
            'subtitle': 'Aucune année détectée dans date de création',
        }

    chart_months = _months_for_recettes_chart(monthly_dict, years)
    if not chart_months:
        return {
            'labels': [],
            'years': years,
            'series': [],
            'y_ticks': [0],
            'y_tick_labels': ['0'],
            'max_value': 0,
            'mode': 'empty',
            'subtitle': 'Aucun montant reçu daté (vérifiez date de création et montant payé)',
        }

    labels = [_MONTH_LABELS[m - 1] for m in chart_months]

    series = []
    max_value = 0
    n = len(chart_months)
    for idx, year in enumerate(years):
        monthly_values = _monthly_values_for_year(monthly_dict, year, chart_months)
        max_value = max(max_value, max(monthly_values) if monthly_values else 0)
        color = _RECETTES_COLORS[idx % len(_RECETTES_COLORS)]
        points = []
        for i, val in enumerate(monthly_values):
            x = (i / (n - 1) * 760) if n > 1 else 380
            py = 230 - (val / max(max_value, 1) * 210) if max_value else 230
            points.append(f'{x:.1f},{py:.1f}')
        series.append({
            'name': str(year),
            'color': color,
            'monthly_values': monthly_values,
            'points': ' '.join(points),
        })

    y_ticks = _nice_y_ticks(max_value)
    y_tick_labels = [_format_fcfa_full(t) for t in y_ticks]

    mode = 'compare' if len(years) >= 2 else 'single_year'
    subtitle = (
        'Montants reçus par mois (date de création) — comparaison par année'
        if mode == 'compare'
        else f'Montants reçus par mois — {years[0]}'
    )

    return {
        'labels': labels,
        'years': years,
        'series': series,
        'y_ticks': y_ticks,
        'y_tick_labels': y_tick_labels,
        'max_value': max_value,
        'mode': mode,
        'subtitle': subtitle,
        'title': 'Comparaison des recettes',
    }


def get_recettes_mensuelles_data(db):
    """
    Recettes mensuelles — TCD montants reçus par (année, mois) selon date_creation.
    Recalcul live depuis sectoriel_import_lines si disponible (évite mois fantômes).
    """
    from models import SectorielImportLine
    from services.consolidation import recompute_monthly_recu_from_sectoriel_lines, load_monthly_recu_dict

    if db.query(SectorielImportLine).count() > 0:
        monthly_dict = recompute_monthly_recu_from_sectoriel_lines(db)
    else:
        ensure_monthly_recu_cached(db)
        monthly_dict = load_monthly_recu_dict(db)
    return _build_recettes_chart_payload(monthly_dict)


# ---------------------------------------------------------------------------
# Historique des traitements
# ---------------------------------------------------------------------------

def _snapshot_display_row(s):
    neants = getattr(s, 'neants', 0) or 0
    declarants = s.declarants or 0
    declarants_total = neants + declarants
    return {
        'date': s.date_run.strftime('%d/%m/%Y %H:%M') if s.date_run else '',
        'total': s.total or 0,
        'defaillants': s.defaillants or 0,
        'neants': neants,
        'relicataires': s.relicataires or 0,
        'declarants': declarants,
        'declarants_total': declarants_total,
        'pct_neants_in_declarants': _pct(neants, declarants_total) if declarants_total else 0.0,
        'taux_declaration': float(s.taux_declaration or 0),
        'sum_montant_attendu': float(s.sum_montant_declare or s.sum_montant_attendu or 0),
        'sum_montant_declare': float(s.sum_montant_declare or 0),
        'sum_montant_recu': float(getattr(s, 'sum_montant_recu', 0) or 0),
        'nb_fichiers': s.nb_fichiers or 0,
    }


def save_treatment_snapshot(db, user='admin', nb_fichiers=0, label=None):
    """Enregistre un instantané après traitement Phase 2."""
    stats = get_global_stats(db)
    cflp_rates = get_cflp_declaration_rates(db)
    taux = stats['taux_declaration']
    snapshot = TreatmentSnapshot(
        user=user,
        total=stats['total'],
        defaillants=stats['defaillants'],
        neants=stats['neants'],
        relicataires=stats['relicataires'],
        declarants=stats['declarants'],
        taux_declaration=taux,
        sum_montant_attendu=stats['sum_montant'],
        sum_montant_declare=stats['sum_declare_attendu'],
        sum_montant_recu=stats['sum_paye'],
        nb_fichiers=nb_fichiers,
        cflp_stats_json=json.dumps(cflp_rates, ensure_ascii=False),
        label=label,
    )
    db.add(snapshot)
    return snapshot


def get_treatment_comparison(db):
    snapshots = db.query(TreatmentSnapshot).order_by(TreatmentSnapshot.date_run.desc()).limit(2).all()
    if not snapshots:
        return None

    current = snapshots[0]
    previous = snapshots[1] if len(snapshots) > 1 else None
    cur = _snapshot_display_row(current)
    prev = _snapshot_display_row(previous) if previous else None
    delta = None
    if prev:
        delta = {
            'defaillants': cur['defaillants'] - prev['defaillants'],
            'relicataires': cur['relicataires'] - prev['relicataires'],
            'declarants': cur['declarants'] - prev['declarants'],
            'neants': cur['neants'] - prev['neants'],
            'taux_declaration': round(cur['taux_declaration'] - prev['taux_declaration'], 1),
            'total': cur['total'] - prev['total'],
            'sum_montant_attendu': cur['sum_montant_attendu'] - prev['sum_montant_attendu'],
            'sum_montant_recu': cur['sum_montant_recu'] - prev['sum_montant_recu'],
        }

    return {
        'current': cur,
        'previous': prev,
        'delta': delta,
        'has_previous': previous is not None,
    }


def get_treatment_history(db, limit=10):
    rows = db.query(TreatmentSnapshot).order_by(TreatmentSnapshot.date_run.desc()).limit(limit).all()
    return [{
        'id': r.id,
        'date': r.date_run.strftime('%d/%m/%Y %H:%M') if r.date_run else '',
        'total': r.total or 0,
        'defaillants': r.defaillants or 0,
        'neants': getattr(r, 'neants', 0) or 0,
        'relicataires': r.relicataires or 0,
        'declarants': r.declarants or 0,
        'declarants_total': (getattr(r, 'neants', 0) or 0) + (r.declarants or 0),
        'taux_declaration': float(r.taux_declaration or 0),
        'nb_fichiers': r.nb_fichiers or 0,
        'user': r.user or '',
    } for r in rows]


# Ordre d'affichage TCD mi-parcours (Secteur CIME)
from services.secteur_cime import (
    CANONICAL_SECTEUR_CIME,
    _normalize_secteur_cime_label,
    canonicalize_secteur_cime,
    display_secteur_cime_rows,
)


def _accumulate_contribuable_in_bucket(bucket, c, count_size=True):
    if count_size:
        bucket['total'] += 1
        bucket['contribuables'] += 1
        bucket['taille_fichier'] += 1
    etat = _sector_tcd_etat(c)
    md = float(c.montant_declare or 0)
    mp = float(c.montant_paye or 0) if c.montant_paye is not None else 0.0
    if etat == ETAT_DEFAILLANT:
        bucket['defaillants'] += 1
    elif etat == ETAT_NEANT:
        bucket['neants'] += 1
    elif etat == ETAT_DECLARANT:
        bucket['declarants'] += 1
    bucket['montant_declare'] += md
    if etat in _ETATS_PAYE:
        bucket['montant_recu'] += mp
    bucket['declarants_total'] = bucket['neants'] + bucket['declarants']
    bucket['declarations'] = bucket['declarants']
    bucket['non_contributeur'] = bucket['defaillants'] + bucket['neants']


def _finalize_bucket_rates(bucket):
    denom = bucket.get('taille_fichier') or bucket['total'] or 0
    bucket['declarants_total'] = bucket['neants'] + bucket['declarants']
    # Taux = declarants (montant > 10) / taille fichier (référence secteurs pour sous-secteur)
    bucket['taux_declaration'] = _pct(bucket['declarants'], denom)
    bucket['taux_non_contributeur'] = _pct(bucket['non_contributeur'], denom)
    bucket['ecart'] = bucket['montant_declare'] - bucket['montant_recu']
    bucket['taux_encaissement'] = _pct(bucket['montant_recu'], bucket['montant_declare'])
    return bucket


def get_taux_declaration_by_secteur(db):
    """
    TCD par Secteur CIME — structure fixe OBNL / POOL / SECTEUR + #N/A uniquement.
    Jamais d'activités brutes (ENSEIGNEMENT, COMMERCE, …).
    """
    display_labels = display_secteur_cime_rows()
    buckets_map = {label: _empty_dimension_bucket(label) for label in display_labels}
    na = _empty_dimension_bucket('#N/A')
    allowed = {label.upper(): label for label in display_labels}

    for c in db.query(Contribuable).all():
        canonical = canonicalize_secteur_cime(c.secteur)
        if not canonical or canonical.upper() not in allowed:
            _accumulate_contribuable_in_bucket(na, c)
        else:
            _accumulate_contribuable_in_bucket(buckets_map[allowed[canonical.upper()]], c)

    buckets = [buckets_map[label] for label in display_labels]
    buckets.append(na)

    for b in buckets:
        _finalize_bucket_rates(b)

    total = _total_row_from_buckets(buckets)
    if total:
        buckets.append(total)
    return buckets


def get_taux_declaration_by_sous_secteur(db):
    """
    TCD par Sous secteur — libellés du fichier secteurs (RECHERCHEV NIU).
    Taille = nombre de NIU dans le fichier secteurs (référence), pas le fichier en ligne.
    """
    from services.sous_secteur_ref import (
        canonical_sous_secteur_label,
        load_sous_secteur_ref_map,
        normalize_sous_secteur_key,
        taille_by_sous_secteur_from_ref,
    )

    ref_map = load_sous_secteur_ref_map(db)
    ref_tailles = taille_by_sous_secteur_from_ref(db)
    buckets_map = {}
    na = _empty_dimension_bucket('#N/A')

    if ref_tailles:
        for key, info in ref_tailles.items():
            bucket = _empty_dimension_bucket(info['label'])
            bucket['taille_fichier'] = info['taille']
            buckets_map[key] = bucket

        online = {c.niu: c for c in db.query(Contribuable).all()}
        for niu, ref in ref_map.items():
            c = online.get(niu)
            if not c:
                continue
            key = normalize_sous_secteur_key(ref.sous_secteur)
            if not key or key not in buckets_map:
                continue
            _accumulate_contribuable_in_bucket(buckets_map[key], c, count_size=False)

        for c in online.values():
            ref = ref_map.get(c.niu)
            if ref and normalize_sous_secteur_key(ref.sous_secteur):
                continue
            _accumulate_contribuable_in_bucket(na, c, count_size=True)
    else:
        # Rétrocompatibilité si référence absente (traitement avant correctif)
        for c in db.query(Contribuable).all():
            raw = (c.sous_secteur or '').strip()
            key = normalize_sous_secteur_key(raw)
            if not key:
                _accumulate_contribuable_in_bucket(na, c)
            else:
                if key not in buckets_map:
                    buckets_map[key] = _empty_dimension_bucket(canonical_sous_secteur_label(raw))
                _accumulate_contribuable_in_bucket(buckets_map[key], c)

    buckets = sorted(
        buckets_map.values(),
        key=lambda b: (
            _SOUS_SECTEUR_ORDER_INDEX.get(_normalize_order_key(b.get('label')), 10_000),
            _normalize_order_key(b.get('label')),
        ),
    )
    if na['taille_fichier'] > 0 or na['contribuables'] > 0:
        buckets.append(na)
    for b in buckets:
        _finalize_bucket_rates(b)
    total = _total_row_from_buckets([b for b in buckets if b['label'] != 'Total général'])
    if total:
        buckets.append(total)
    return buckets


def _empty_reliquataire_sous_secteur_bucket(label):
    return {
        'label': label,
        'reliquataires': 0,
        'montant_reliquataires': 0.0,
        'emissions': 0.0,
        'ratio_reliquataires': 0.0,
    }


def _accumulate_reliquataire_sous_secteur(bucket, c):
    """Reliquataire = état 2 · émissions = somme montant_declare du sous-secteur."""
    etat = _etat_bucket(c)
    md = float(c.montant_declare or 0)
    bucket['emissions'] += md
    if etat == ETAT_RELICATAIRE:
        bucket['reliquataires'] += 1
        bucket['montant_reliquataires'] += md


def _finalize_reliquataire_sous_secteur(bucket):
    bucket['ratio_reliquataires'] = _pct(bucket['montant_reliquataires'], bucket['emissions'])
    return bucket


def _total_reliquataire_row_from_buckets(buckets, label='Total général'):
    if not buckets:
        return None
    rel = sum(b.get('reliquataires', 0) for b in buckets)
    mont = sum(b.get('montant_reliquataires', 0.0) for b in buckets)
    em = sum(b.get('emissions', 0.0) for b in buckets)
    return {
        'label': label,
        'reliquataires': rel,
        'montant_reliquataires': mont,
        'emissions': em,
        'ratio_reliquataires': _pct(mont, em),
    }


def get_reliquataires_by_sous_secteur(db):
    """
    Reliquataires et émissions par sous-secteur — fichier en ligne + RECHERCHEV secteurs.

    - Reliquataires : nombre d'état 2 (déclaré, rien payé)
    - Montant reliquataires : somme montant_declare (état 2)
    - Emissions : somme montant_declare (tous états)
    - Ratio des reliquataires : (Montant reliquataires / Emissions) × 100
    """
    from services.sous_secteur_ref import (
        canonical_sous_secteur_label,
        load_sous_secteur_ref_map,
        normalize_sous_secteur_key,
        taille_by_sous_secteur_from_ref,
    )

    ref_map = load_sous_secteur_ref_map(db)
    ref_tailles = taille_by_sous_secteur_from_ref(db)
    buckets_map = {}
    na = _empty_reliquataire_sous_secteur_bucket('#N/A')

    if ref_tailles:
        for key, info in ref_tailles.items():
            buckets_map[key] = _empty_reliquataire_sous_secteur_bucket(info['label'])

        online = {c.niu: c for c in db.query(Contribuable).all()}
        for niu, ref in ref_map.items():
            c = online.get(niu)
            if not c:
                continue
            key = normalize_sous_secteur_key(ref.sous_secteur)
            if not key or key not in buckets_map:
                continue
            _accumulate_reliquataire_sous_secteur(buckets_map[key], c)

        for c in online.values():
            ref = ref_map.get(c.niu)
            if ref and normalize_sous_secteur_key(ref.sous_secteur):
                continue
            _accumulate_reliquataire_sous_secteur(na, c)
    else:
        for c in db.query(Contribuable).all():
            raw = (c.sous_secteur or '').strip()
            key = normalize_sous_secteur_key(raw)
            if not key:
                _accumulate_reliquataire_sous_secteur(na, c)
            else:
                if key not in buckets_map:
                    buckets_map[key] = _empty_reliquataire_sous_secteur_bucket(
                        canonical_sous_secteur_label(raw)
                    )
                _accumulate_reliquataire_sous_secteur(buckets_map[key], c)

    buckets = sorted(
        buckets_map.values(),
        key=lambda b: (
            _SOUS_SECTEUR_ORDER_INDEX.get(_normalize_order_key(b.get('label')), 10_000),
            _normalize_order_key(b.get('label')),
        ),
    )
    if na['emissions'] or na['reliquataires']:
        buckets.append(na)
    for b in buckets:
        _finalize_reliquataire_sous_secteur(b)
    total = _total_reliquataire_row_from_buckets(buckets)
    if total:
        buckets.append(total)
    return buckets


def get_taux_declaration_by_structure(db):
    """Taux de déclaration par CFLP (structure)."""
    raw = _aggregate_dimension(db, Contribuable.cdi)
    buckets = []
    for label in get_all_cflp_labels():
        if label in raw:
            buckets.append(raw[label])
        else:
            buckets.append(_empty_dimension_bucket(label))
    for label, data in raw.items():
        if label not in get_all_cflp_labels() and label != 'N/A':
            buckets.append(data)
    buckets.sort(key=lambda x: (-x['total'], x['label']))
    total = _total_row_from_buckets(buckets)
    if total:
        buckets.append(total)
    return buckets


def get_performance_by_cflp(db):
    """Performance par centre CFLP — montants déclarés vs reçus."""
    raw = _aggregate_dimension(db, Contribuable.cdi)
    buckets = []
    for label in get_all_cflp_labels():
        buckets.append(raw.get(label) or _empty_dimension_bucket(label))
    for label, data in raw.items():
        if label not in get_all_cflp_labels() and label != 'N/A':
            buckets.append(data)
    buckets.sort(key=lambda x: (-x['montant_declare'], x['label']))
    total = _total_row_from_buckets(buckets)
    if total:
        buckets.append(total)
    return buckets


def get_montants_by_secteur(db):
    raw = _aggregate_dimension(db, Contribuable.secteur)
    buckets = list(raw.values())
    buckets.sort(key=lambda x: (-x['montant_declare'], x['label']))
    total = _total_row_from_buckets(buckets)
    if total:
        buckets.append(total)
    return buckets


# ---------------------------------------------------------------------------
# Recherche & filtres
# ---------------------------------------------------------------------------

def search_contribuables(db, q='', cdi='', secteur='', etat='', statut='', limit=50):
    query = db.query(Contribuable)
    if q:
        query = query.filter(
            or_(Contribuable.niu.ilike(f'%{q}%'), Contribuable.raison.ilike(f'%{q}%'))
        )
    if cdi and cdi not in ('', 'Tous les CFLP', 'Tous les CDI', 'Tous les centres'):
        cdi_val = normalize_cdi(cdi) or cdi
        query = query.filter(or_(Contribuable.cdi == cdi_val, Contribuable.cdi == cdi))
    if secteur and secteur not in ('', 'Tous les secteurs', 'Tous Secteurs'):
        query = query.filter(Contribuable.secteur == secteur)
    if etat and str(etat).isdigit():
        query = query.filter(Contribuable.etat == int(etat))
    if statut and statut not in ('', 'Tous les statuts'):
        statut_map = {
            'Défaillant': ETAT_DEFAILLANT,
            'Non déclaré': ETAT_DEFAILLANT,
            'Néant': ETAT_NEANT,
            'Relicataire': ETAT_RELICATAIRE,
            'Déclaré': ETAT_RELICATAIRE,
            'Déclarant': ETAT_DECLARANT,
            'Déclarants': ETAT_DECLARANT,
            'Payé': ETAT_DECLARANT,
        }
        if statut in statut_map:
            if statut in ('Déclarant', 'Déclarants', 'Payé'):
                query = query.filter(Contribuable.etat.in_([ETAT_NEANT, ETAT_DECLARANT]))
            else:
                query = query.filter(Contribuable.etat == statut_map[statut])
    total = query.count()
    results = query.order_by(Contribuable.raison).limit(limit).all()
    return results, total


def get_filter_options(db):
    cdi_rows = db.query(Contribuable.cdi).filter(
        Contribuable.cdi.isnot(None), Contribuable.cdi != ''
    ).distinct().all()
    sect_rows = db.query(Contribuable.secteur).filter(
        Contribuable.secteur.isnot(None), Contribuable.secteur != ''
    ).distinct().all()
    db_cdis = [normalize_cdi(r[0]) or r[0] for r in cdi_rows if r[0]]
    known = set(get_all_cflp_labels())
    cflp_list = sorted(known | set(db_cdis))
    cflp_extra = sorted(set(db_cdis) - known)
    return {
        'cflp_centres': get_all_cflp_labels(),
        'cflp_groups': CFLP_GROUPS,
        'cflp_list': cflp_list,
        'cflp_extra': cflp_extra,
        'secteur_list': sorted([r[0] for r in sect_rows if r[0]]),
    }


# ---------------------------------------------------------------------------
# Listes par statut
# ---------------------------------------------------------------------------

def get_defaillants(db, limit=None):
    rows = _contribuables_by_etat(db, ETAT_DEFAILLANT)
    return rows[:limit] if limit else rows


def get_neants(db, limit=None):
    rows = _contribuables_by_etat(db, ETAT_NEANT)
    return rows[:limit] if limit else rows


def get_declarants(db, limit=None):
    """Déclarants = état 3 (montant > 10 et payé)."""
    rows = _contribuables_by_etat(db, ETAT_DECLARANT)
    return rows[:limit] if limit else rows


def get_non_declarants(db, limit=None):
    return get_defaillants(db, limit)


def get_relicataires(db, limit=None):
    rows = _contribuables_by_etat(db, ETAT_RELICATAIRE)
    return rows[:limit] if limit else rows


def get_statut_label(etat):
    return ETAT_LABELS.get(etat, 'Inconnu')


def _format_montant_paye_display(c):
    if c.etat == ETAT_RELICATAIRE:
        return 'N/A'
    if c.montant_paye is None:
        return 'N/A'
    return c.montant_paye


def _contribuable_row(c, statut=None):
    cflp = normalize_cdi(c.cdi) or c.cdi or ''
    montant_paye = _format_montant_paye_display(c)
    return {
        'NIU': c.niu,
        'Raison': c.raison or '',
        'CFLP': cflp,
        'CDI': cflp,
        'Secteur': c.secteur or '',
        'Montant attendu': c.montant_attendu,
        'Montant déclaré': c.montant_declare if c.montant_declare is not None else 0,
        'Montant payé': montant_paye,
        'Statut': statut or get_statut_label(c.etat),
        'niu': c.niu,
        'raison': c.raison or '-',
        'cdi': cflp,
        'secteur': c.secteur or '',
        'montant_declare': c.montant_declare if c.montant_declare is not None else 0,
        'montant_attendu': c.montant_attendu,
    }


def get_list_export_rows(db, etat, statut_label):
    return [
        _contribuable_row(c, statut_label)
        for c in _contribuables_by_etat(db, etat)
    ]


def get_defaillants_export_rows(db):
    return get_list_export_rows(db, ETAT_DEFAILLANT, 'Défaillant')


def get_neants_export_rows(db):
    return get_list_export_rows(db, ETAT_NEANT, 'Néant')


def get_declarants_export_rows(db):
    return get_list_export_rows(db, ETAT_DECLARANT, 'Déclarant')


def get_relicataires_export_rows(db):
    return get_list_export_rows(db, ETAT_RELICATAIRE, 'Relicataire')


# ---------------------------------------------------------------------------
# Export statistiques (Excel / PDF)
# ---------------------------------------------------------------------------

def build_export_stats_data(db):
    stats = get_global_stats(db)
    by_cdi = get_by_cdi(db)
    by_sect = get_by_secteur(db)
    by_etat = get_by_etat(db)
    taux_secteur = get_taux_declaration_by_secteur(db)
    taux_structure = get_taux_declaration_by_structure(db)
    performance_cflp = get_performance_by_cflp(db)
    montants_secteur = get_montants_by_secteur(db)

    global_rows = [
        {'metrique': 'Total contribuables (en ligne)', 'valeur': stats['total']},
        {'metrique': 'Défaillants (#N/A)', 'valeur': stats['defaillants']},
        {'metrique': 'Relicataires (ont déclaré, rien payé — N/A)', 'valeur': stats['relicataires']},
        {'metrique': 'Déclarants (total)', 'valeur': stats['declarants_total']},
        {'metrique': f'… dont néants (0 à {int(MONTANT_NEANT_MAX)} FCFA)', 'valeur': stats['neants']},
        {'metrique': f'… dont {stats["pct_neants_in_declarants"]}% néants dans les déclarants', 'valeur': stats['pct_neants_in_declarants']},
        {'metrique': 'Montant attendu — déclaré (FCFA)', 'valeur': stats['sum_declare_attendu']},
        {'metrique': 'Montant reçu — payé (FCFA)', 'valeur': stats['sum_paye']},
        {'metrique': 'Taux d\'encaissement (%)', 'valeur': _pct(stats['sum_paye'], stats['sum_declare_attendu'])},
    ]

    cdi_rows = [{
        'CFLP': r['cdi'],
        'Déclarants': r['declarants'] + r.get('neants', 0),
        'Dont néants': r.get('neants', 0),
        'Relicataires': r['relicataires'],
        'Défaillants': r['defaillants'],
        'Montant': r['montant'],
    } for r in by_cdi]

    sect_rows = [
        {'Secteur': r['secteur'], 'Nombre': r['count'], 'Montant déclaré': r['montant']}
        for r in by_sect
    ]
    etat_rows = [
        {'Catégorie': r['label'], 'Nombre': r['count'], 'Montant': r['montant']}
        for r in by_etat
    ]

    defaillants_rows = [{
        'NIU': r['NIU'], 'Raison': r['Raison'], 'CFLP': r['CFLP'], 'Statut': r['Statut'],
    } for r in get_defaillants_export_rows(db)]

    relicataires_rows = [{
        'NIU': r['NIU'], 'Raison': r['Raison'],
        'Montant déclaré': r['Montant déclaré'], 'CFLP': r['CFLP'], 'Statut': r['Statut'],
    } for r in get_relicataires_export_rows(db)]

    declarants_rows = [{
        'NIU': r['NIU'], 'Raison': r['Raison'],
        'Montant déclaré': r['Montant déclaré'], 'Montant payé': r['Montant payé'],
        'Catégorie': r['Statut'], 'CFLP': r['CFLP'],
    } for r in get_declarants_export_rows(db)]

    return {
        'global': global_rows,
        'cdi': cdi_rows,
        'secteur': sect_rows,
        'etat': etat_rows,
        'defaillants': defaillants_rows,
        'relicataires': relicataires_rows,
        'declarants': declarants_rows,
        'non_declarants': defaillants_rows,
        'taux_secteur': taux_secteur,
        'taux_structure': taux_structure,
        'performance_cflp': performance_cflp,
        'montants_secteur': montants_secteur,
        'stats': stats,
    }
