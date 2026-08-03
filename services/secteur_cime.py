"""Catalogue Secteur CIME — libellés autorisés (fichier secteurs, étape 5)."""

from models import SecteurCimeCatalog

# Structure fixe du TCD mi-parcours CRIC EXT (comme Excel manuel)
CANONICAL_SECTEUR_CIME = [
    'OBNL',
    'POOL 1', 'POOL 2', 'POOL 3',
    'SECTEUR 1', 'SECTEUR 2', 'SECTEUR 3', 'SECTEUR 4', 'SECTEUR 5',
]

SECTEUR_CIME_ORDER = CANONICAL_SECTEUR_CIME + ['#N/A', 'N/A']


def _normalize_secteur_cime_label(label):
    if not label or str(label).strip().upper() in ('', 'N/A', 'NA', '#N/A'):
        return '#N/A'
    return str(label).strip()


def _sort_key(label):
    norm = (label or '').strip().upper()
    for idx, known in enumerate(SECTEUR_CIME_ORDER):
        if norm == known.upper():
            return idx
    return len(SECTEUR_CIME_ORDER) + 1


def canonicalize_secteur_cime(raw):
    """
    Normalise un libellé fichier vers OBNL / POOL n / SECTEUR n.
    Retourne None si le libellé n'est pas un Secteur CIME reconnu.
    """
    if raw is None or _normalize_secteur_cime_label(raw) == '#N/A':
        return None
    s = str(raw).strip().upper()
    s = s.replace('_', ' ').replace('-', ' ')
    s = ' '.join(s.split())
    aliases = {
        'OBNL': 'OBNL',
        'POOL1': 'POOL 1', 'POOL 1': 'POOL 1',
        'POOL2': 'POOL 2', 'POOL 2': 'POOL 2',
        'POOL3': 'POOL 3', 'POOL 3': 'POOL 3',
        'SECTEUR1': 'SECTEUR 1', 'SECTEUR 1': 'SECTEUR 1',
        'SECTEUR2': 'SECTEUR 2', 'SECTEUR 2': 'SECTEUR 2',
        'SECTEUR3': 'SECTEUR 3', 'SECTEUR 3': 'SECTEUR 3',
        'SECTEUR4': 'SECTEUR 4', 'SECTEUR 4': 'SECTEUR 4',
        'SECTEUR5': 'SECTEUR 5', 'SECTEUR 5': 'SECTEUR 5',
    }
    if s in aliases:
        return aliases[s]
    for canonical in CANONICAL_SECTEUR_CIME:
        if s == canonical.upper():
            return canonical
    return None


def save_secteur_cime_catalog(db, labels, commit=True):
    """Enregistre les Secteurs CIME distincts du fichier (RECHERCHEV étape 5)."""
    db.query(SecteurCimeCatalog).delete()
    seen = set()
    found = []
    for raw in labels or []:
        canonical = canonicalize_secteur_cime(raw)
        if not canonical or canonical.upper() in seen:
            continue
        seen.add(canonical.upper())
        found.append(canonical)
    if not found:
        found = list(CANONICAL_SECTEUR_CIME)
    found.sort(key=lambda x: (_sort_key(x), x.upper()))
    for i, label in enumerate(found):
        db.add(SecteurCimeCatalog(label=label, sort_order=i))
    if commit:
        db.commit()
    return found


def load_secteur_cime_catalog(db):
    rows = db.query(SecteurCimeCatalog).order_by(SecteurCimeCatalog.sort_order).all()
    if rows:
        return [r.label for r in rows]
    return list(CANONICAL_SECTEUR_CIME)


def clear_secteur_cime_catalog(db, commit=True):
    db.query(SecteurCimeCatalog).delete()
    if commit:
        db.commit()


def display_secteur_cime_rows():
    """Lignes du TCD — structure fixe + #N/A (jamais d'activités brutes)."""
    return list(CANONICAL_SECTEUR_CIME)
