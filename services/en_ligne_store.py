"""Persistance du fichier en ligne (modèle NHR) pour export RECHERCHEV."""
import json
import os

import pandas as pd

from models import EnLigneLine, EnLigneMeta
from niu import is_valid_niu, normalize_niu


def _cell_export_value(val):
    if val is None:
        return ''
    try:
        if pd.isna(val):
            return ''
    except (TypeError, ValueError):
        pass
    if isinstance(val, str):
        return val.strip()
    return val


def _find_niu_column_raw(df):
    """Repère la colonne NIU dans un DataFrame aux en-têtes d'origine."""
    from import_utils import _normalize_col

    for col in df.columns:
        nc = _normalize_col(str(col))
        if nc in ('niu', 'identifiant_unique', 'num_niu', 'matricule', 'numero_niu'):
            return col
        if 'niu' in nc and 'montant' not in nc:
            return col
    return None


def _filter_valid_niu_raw(df, niu_col):
    def _ok(val):
        n = normalize_niu(str(val or '').strip())
        return is_valid_niu(n)

    mask = df[niu_col].apply(_ok)
    return df[mask].copy()


def clear_en_ligne_artifacts(db, commit=True):
    db.query(EnLigneLine).delete()
    db.query(EnLigneMeta).delete()
    if commit:
        db.commit()


def persist_en_ligne_files(db, filepaths):
    """
    Sauvegarde les lignes du fichier en ligne avec en-têtes d'origine (modèle NHR).
    Appelé en phase 2 avant la RECHERCHEV.
    """
    from import_utils import read_dataframe

    clear_en_ligne_artifacts(db, commit=False)
    headers = None
    source_label = None
    row_order = 0

    for fp in filepaths:
        if not fp or not os.path.isfile(fp):
            continue
        df_raw = read_dataframe(fp)
        if df_raw is None or df_raw.empty:
            continue

        file_headers = [str(c) for c in df_raw.columns]
        niu_col = _find_niu_column_raw(df_raw)
        if not niu_col:
            continue

        df_valid = _filter_valid_niu_raw(df_raw, niu_col)
        df_valid = df_valid.drop_duplicates(subset=[niu_col], keep='first')

        if headers is None:
            headers = file_headers
            source_label = os.path.basename(fp)
            db.add(EnLigneMeta(
                headers_json=json.dumps(headers, ensure_ascii=False),
                source_filename=source_label,
                sectors_applied=0,
            ))
        elif file_headers != headers:
            # Fichiers multiples : aligner sur les en-têtes du premier fichier
            pass

        use_headers = headers or file_headers
        for _, row in df_valid.iterrows():
            niu = normalize_niu(str(row[niu_col] or '').strip())
            if not is_valid_niu(niu):
                continue
            values = []
            for h in use_headers:
                if h in row.index:
                    values.append(_cell_export_value(row[h]))
                else:
                    values.append('')
            db.add(EnLigneLine(
                row_order=row_order,
                niu=niu,
                values_json=json.dumps(values, ensure_ascii=False),
            ))
            row_order += 1

    db.flush()
    return row_order


def load_en_ligne_headers(db):
    meta = db.query(EnLigneMeta).order_by(EnLigneMeta.id.desc()).first()
    if not meta or not meta.headers_json:
        return []
    try:
        return json.loads(meta.headers_json)
    except (json.JSONDecodeError, TypeError):
        return []


def load_en_ligne_lines(db):
    return db.query(EnLigneLine).order_by(EnLigneLine.row_order).all()


def mark_sectors_applied(db, commit=False):
    meta = db.query(EnLigneMeta).order_by(EnLigneMeta.id.desc()).first()
    if meta:
        meta.sectors_applied = 1
        if commit:
            db.commit()
        else:
            db.flush()


def sectors_applied(db):
    meta = db.query(EnLigneMeta).order_by(EnLigneMeta.id.desc()).first()
    return bool(meta and getattr(meta, 'sectors_applied', 0))
