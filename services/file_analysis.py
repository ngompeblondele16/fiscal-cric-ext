"""Validation des fichiers Excel à l'upload (wizard Import)."""
from import_utils import inspect_upload_file, _has_sector_lookup_column

_REQUIRED_SECTOR = {'niu', 'montant'}
# Fichier en ligne = liste de référence pour RECHERCHEV (montant vient du consolidé)
_REQUIRED_ONLINE = {'niu'}


def _label_col(col):
    return col.replace('_', ' ').title()


def analyze_upload_file(filepath, expected_phase=1):
    """
    Validation après une seule lecture du fichier.
    Retourne type, lignes et erreurs bloquantes uniquement (sans liste de colonnes).
    """
    if expected_phase == 4:
        from services.ca_analysis import inspect_ca_upload_fast
        return inspect_ca_upload_fast(filepath)

    ftype, cols, nb_rows = inspect_upload_file(filepath)
    cols = set(cols or [])
    errors = []

    if ftype == 'unknown':
        errors.append('Format non reconnu — vérifiez NIU et colonnes montant.')

    if expected_phase == 1:
        missing = _REQUIRED_SECTOR - cols
        if missing:
            errors.append('Colonnes obligatoires manquantes : ' + ', '.join(_label_col(c) for c in sorted(missing)))
        if ftype == 'en_ligne':
            errors.append('Fichier en ligne détecté — utilisez l’étape « Fichier en ligne ».')
    elif expected_phase == 2:
        missing = _REQUIRED_ONLINE - cols
        if missing:
            errors.append('Colonnes obligatoires manquantes : ' + ', '.join(_label_col(c) for c in sorted(missing)))
        elif ftype == 'sectoriel' and 'montant' in cols:
            errors.append('Fichier sectoriel détecté — utilisez l’étape « Fichiers déclaratifs ».')
        elif ftype == 'unknown':
            errors.append('Format non reconnu — vérifiez la colonne NIU.')
    elif expected_phase == 3:
        if 'niu' not in cols:
            errors.append('Colonne NIU obligatoire pour le fichier secteurs.')
        if not _has_sector_lookup_column(cols):
            errors.append('Colonne « Secteur CIME » obligatoire (pas la colonne activité / secteur métier).')

    return {
        'file_type': ftype,
        'nb_rows': nb_rows,
        'errors': errors,
        'ok': len(errors) == 0,
    }
