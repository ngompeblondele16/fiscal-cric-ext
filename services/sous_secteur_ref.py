"""Référence sous-secteurs — fichier secteurs (RECHERCHEV étape 5)."""
import unicodedata
from collections import defaultdict

from models import SousSecteurRef

# Libellés officiels (source unique d'affichage des sous-secteurs).
_SS_OFFICIAL_LABELS = [
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
]

# Variantes (singulier/pluriel, fautes) ramenées à une clé unique.
_SS_KEY_ALIASES = {
    'SERVICE MARCHANDS': 'SERVICES MARCHANDS',
    'SERVICES NON MARCHANDS': 'SERVICE NON MARCHANDS',
    'INDUSTRIES MANUFACTURIERES': 'INDUSTRIES MANUFASTURIERES',
}


def _strip_accents(value):
    return ''.join(
        c for c in unicodedata.normalize('NFKD', value)
        if not unicodedata.combining(c)
    )


def normalize_sous_secteur_key(label):
    # Clé de regroupement : majuscules, sans accents, espaces réduits, alias appliqués.
    # « service marchands » et « Services marchands » donnent donc la même clé.
    if not label or str(label).strip().upper() in ('', 'N/A', 'NA', '#N/A'):
        return ''
    norm = _strip_accents(' '.join(str(label).strip().split()).upper())
    # Règle robuste : toutes les variantes « (services) marchands » fusionnent.
    if 'MARCHAND' in norm:
        return 'SERVICE NON MARCHANDS' if 'NON MARCHAND' in norm else 'SERVICES MARCHANDS'
    return _SS_KEY_ALIASES.get(norm, norm)


# clé normalisée -> libellé officiel d'affichage
_SS_OFFICIAL_BY_KEY = {
    normalize_sous_secteur_key(lbl): lbl for lbl in _SS_OFFICIAL_LABELS
}


def canonical_sous_secteur_label(label):
    # Libellé d'affichage unique pour un sous-secteur (officiel si connu).
    key = normalize_sous_secteur_key(label)
    if not key:
        return '#N/A'
    return _SS_OFFICIAL_BY_KEY.get(key, ' '.join(str(label).strip().split()))


def clear_sous_secteur_ref(db, commit=False):
    db.query(SousSecteurRef).delete()
    if commit:
        db.commit()


def save_sous_secteur_ref(db, niu_to_sous_secteur, niu_to_secteur=None, commit=False):
    """Persiste le mapping NIU → sous-secteur lu dans le fichier secteurs."""
    clear_sous_secteur_ref(db, commit=False)
    secteur_map = niu_to_secteur or {}
    rows = []
    for niu, sous in (niu_to_sous_secteur or {}).items():
        label = (sous or '').strip()
        if not label or label.upper() in ('N/A', 'NA', '#N/A'):
            continue
        rows.append(SousSecteurRef(
            niu=niu,
            sous_secteur=label,
            secteur_cime=(secteur_map.get(niu) or '').strip() or None,
        ))
    if rows:
        db.bulk_save_objects(rows)
    if commit:
        db.commit()
    return len(rows)


def load_sous_secteur_ref_map(db):
    return {r.niu: r for r in db.query(SousSecteurRef).all()}


def taille_by_sous_secteur_from_ref(db):
    """
    Taille TCD = nombre de NIU dans le fichier secteurs par sous-secteur.
    Retourne {clé_normalisée: {'label': libellé affiché, 'taille': int}}.
    """
    counts = defaultdict(int)
    labels = {}
    for r in db.query(SousSecteurRef).all():
        key = normalize_sous_secteur_key(r.sous_secteur)
        if not key:
            continue
        counts[key] += 1
        # libellé canonique unique (évite le doublon singulier/pluriel)
        labels.setdefault(key, canonical_sous_secteur_label(r.sous_secteur))
    return {
        key: {'label': labels[key], 'taille': counts[key]}
        for key in counts
    }
