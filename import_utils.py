import pandas as pd
import os
import json
import unicodedata
import re
import gc
import time
from niu import is_valid_niu, normalize_niu
from cdi_config import normalize_cdi, infer_cdi_from_text, get_all_cdi_labels, _normalize_key
from models import Contribuable, Declaration, Paiement, ImportHistory, StateHistory
from datetime import datetime
from fiscal_constants import (
    MONTANT_NEANT_MAX, ETAT_DEFAILLANT, ETAT_NEANT, ETAT_RELICATAIRE, ETAT_DECLARANT,
    ETAT_LABELS, classify_from_declaration,
)

CONSOLIDATED_DIR = os.environ.get('UPLOAD_DIR', 'uploads')
try:
    from config import UPLOAD_DIR as _UPLOAD_DIR
    CONSOLIDATED_DIR = _UPLOAD_DIR
except ImportError:
    pass


def safe_remove_file(path, retries=6, delay=0.2):
    """Supprime un fichier en libérant les verrous Windows (openpyxl / Excel)."""
    if not path or not os.path.isfile(path):
        return True
    last_error = None
    for attempt in range(retries):
        try:
            gc.collect()
            os.remove(path)
            return True
        except OSError as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(delay)
    if last_error:
        raise last_error
    return False


STANDARD_COLUMNS = {
    'niu': ['niu', 'identifiant_unique', 'num_niu', 'matricule', 'numero_niu', 'n_i_u', 'identifiant'],
    'raison_sociale': [
        'raison_sociale', 'raison_social', 'raison', 'nom', 'nom_contribuable', 'nom_du_contribuable',
        'nom_raison_sociale', 'nom_de_contribuable', 'denomination', 'denomination_sociale',
        'contribuable', 'nom_et_prenom', 'nom_et_prenoms', 'nom_prenom', 'libelle', 'intitule',
        'designation', 'rs', 'nom_du_contribuable_ou_raison_sociale', 'redevable', 'nom_du_redevable',
        'nom_ou_raison_sociale', 'nom_raison', 'entreprise', 'societe', 'name', 'names', 'noms',
    ],
    'secteur_cime': [
        'secteur_cime', 'secteurcime', 'secteur_de_cime', 'secteur_du_cime',
        'secteur_cime_cime', 'secteur_sim', 'secteurs_cime', 'secteur_cime_',
    ],
    'secteur': ['secteur', 'secteur_activite', 'secteur_d_activite', 'secteur_dactivite', 'activite', 'activite_principale'],
    'sous_secteur': ['sous_secteur', 'soussecteur', 'sous_secteur_activite'],
    'cdi': ['cdi', 'centre_des_impots', 'centre_impots', 'centre', 'centre_fiscal', 'centre_impot', 'cflp', 'cfpl', 'centre_de_rattachement'],
    'montant': [
        'montant_a_payer', 'montant_apayer', 'montant_a_payer_',
        'montant_du', 'montant_reference', 'montant_declare',
        'montant', 'montant_attendu',
    ],
    'montant_paye': [
        'montant_paye', 'montant_paid', 'montant_verse', 'montant_paye_',
        'montant_recu', 'montant_reçu', 'montant_recu_', 'montant_percu', 'montant_encaisse',
    ],
    'etat': ['etat', 'etat_fiscal', 'state', 'statut_fiscal', 'statut', 'code_etat', 'etat_dossier', 'etat_contribuable'],
    'somme_totale_declaree': ['somme_totale_declaree', 'somme_declaree', 'somme', 'montant_declare'],
    'date_creation': [
        'date_creation', 'date_de_creation', 'datecrea', 'date_crea',
        'date_declaration', 'date_de_declaration', 'date_declaree',
        'date_du_depot', 'date_depot', 'date_enregistrement',
        'date_de_la_creation', 'date_creation_declaration', 'date_du_depot_de_la_declaration',
    ],
    'date_paiement': ['date_paiement', 'date_de_paiement', 'date_paye'],
}


def _column_matches(col, aliases):
    if col in aliases:
        return True
    for alias in aliases:
        if len(alias) >= 3 and (col.startswith(alias + '_') or alias.startswith(col + '_')):
            return True
    if 'raison' in col and ('social' in col or 'sociale' in col):
        return 'raison_sociale' in aliases or 'raison' in aliases
    if col in ('contribuable', 'libelle', 'intitule', 'designation', 'rs', 'entreprise', 'societe', 'name', 'names', 'noms'):
        return 'raison_sociale' in aliases or 'nom' in aliases
    if (col.startswith('nom') or col.startswith('noms')) and 'montant' not in col and 'niu' not in col:
        return 'nom' in aliases or 'raison_sociale' in aliases
    if 'contribuable' in col and 'niu' not in col and 'montant' not in col:
        return 'raison_sociale' in aliases or 'nom' in aliases
    if col.startswith('libelle') or col.startswith('intitule'):
        return 'raison_sociale' in aliases or 'nom' in aliases
    return False


def _count_col_filled(df, col):
    if df is None or col not in df.columns:
        return 0
    return int(df[col].apply(lambda x: not _cell_is_empty(x)).sum())


def _is_raison_like_column(nc):
    if not nc:
        return False
    if nc in STANDARD_COLUMNS['raison_sociale']:
        return True
    if (nc.startswith('nom') or nc.startswith('noms')) and 'montant' not in nc and 'niu' not in nc:
        return True
    if nc in ('name', 'names', 'noms', 'entreprise', 'societe', 'contribuable', 'libelle', 'intitule', 'designation', 'rs', 'redevable'):
        return True
    if 'redevable' in nc and 'niu' not in nc:
        return True
    if 'raison' in nc and ('social' in nc or 'sociale' in nc or nc == 'raison'):
        return True
    if nc.startswith('raison_sociale') or nc.startswith('nomcontribuable'):
        return True
    if 'contribuable' in nc and 'niu' not in nc and 'montant' not in nc:
        return True
    if nc.startswith('libelle') or nc.startswith('intitule'):
        return True
    return False


def _is_non_name_column(nc):
    if nc in (
        'niu', 'etat', 'montant', 'montant_paye', 'secteur', 'secteur_cime', 'sous_secteur', 'cdi', 'regime',
        'ville', 'quartier', 'lieux_dit', 'activite', 'code', 'date_creation', 'date_paiement', 'state', 'statut',
    ):
        return True
    if nc.startswith(('montant', 'etat_', 'statut', 'date_', 'code_', 'numero_', 'num_', 'nb_', 'nbr_')):
        return True
    if 'niu' in nc or nc.endswith('_niu'):
        return True
    return False


_ETAT_VALUE_HINTS = frozenset({
    '0', '1', '2', '3', 'paye', 'paid', 'neant', 'relicataire', 'non', 'nondeclare',
    'nondeclarant', 'declarant', 'defaillant', 'oui', 'yes', 'no',
})


def _is_etat_like_value(val):
    if _cell_is_empty(val):
        return False
    norm = _normalize_col(str(val)).replace('_', '')
    if norm in _ETAT_VALUE_HINTS:
        return True
    return bool(re.fullmatch(r'\d+', norm))


def _looks_like_name_value(val):
    if _cell_is_empty(val):
        return False
    s = str(val).strip()
    if len(s) < 2:
        return False
    if is_valid_niu(normalize_niu(s)):
        return False
    if _is_etat_like_value(s):
        return False
    if re.match(r'^[\d\s.,\-]+$', s):
        return False
    return True


def _score_column_as_name(df, col):
    """Score une colonne selon son contenu textuel (noms d'entreprise probables)."""
    if df is None or col not in df.columns:
        return 0
    nc = _normalize_col(str(col))
    if _is_non_name_column(nc):
        return 0
    score = 500 if _is_raison_like_column(nc) else 0
    for val in df[col]:
        if _looks_like_name_value(val):
            score += min(len(str(val).strip()), 80)
    return score


def _find_raison_column(columns, df=None):
    """Repère la colonne nom / raison sociale (la plus remplie si df fourni)."""
    cols = list(columns)
    candidates = []
    for col in cols:
        nc = col if re.match(r'^[a-z0-9_]+$', str(col or '')) else _normalize_col(str(col))
        if _is_non_name_column(nc):
            continue
        if _is_raison_like_column(nc):
            candidates.append(col)

    if df is not None and candidates:
        candidates.sort(key=lambda c: (_score_column_as_name(df, c), _count_col_filled(df, c)), reverse=True)
        if _score_column_as_name(df, candidates[0]) > 0 or _count_col_filled(df, candidates[0]) > 0:
            return candidates[0]
    if candidates:
        return candidates[0]

    if df is not None:
        niu_idx = next(
            (i for i, c in enumerate(cols) if c == 'niu' or _normalize_col(str(c)) in ('niu', 'num_niu', 'matricule')),
            None,
        )
        if niu_idx is not None:
            for j in range(niu_idx + 1, min(niu_idx + 8, len(cols))):
                col = cols[j]
                nc = _normalize_col(str(col))
                if _is_non_name_column(nc):
                    continue
                if _count_col_filled(df, col) > 0 and _score_column_as_name(df, col) > 0:
                    return col

        scored = []
        for col in cols:
            s = _score_column_as_name(df, col)
            if s > 0:
                scored.append((col, s))
        if scored:
            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[0][0]
    return None


def _ensure_raison_column(df):
    """Garantit une colonne raison_sociale remplie (même si l'en-tête varie)."""
    if df is None or df.empty:
        return df

    raison_col = _find_raison_column(df.columns, df)
    if not raison_col:
        return df

    if 'raison_sociale' not in df.columns:
        if raison_col == 'raison':
            return df.rename(columns={'raison': 'raison_sociale'})
        return df.rename(columns={raison_col: 'raison_sociale'})

    filled = _count_col_filled(df, 'raison_sociale')
    if raison_col in ('raison_sociale', 'raison') and filled > 0:
        return df

    if raison_col in ('raison_sociale', 'raison') and filled == 0:
        alt = _find_raison_column([c for c in df.columns if c != 'raison_sociale'], df)
        if alt:
            raison_col = alt
        else:
            content_col = _find_raison_column(df.columns, df)
            if content_col and content_col != 'raison_sociale':
                raison_col = content_col
            else:
                return df

    existing_fill = _count_col_filled(df, 'raison_sociale')
    new_fill = _count_col_filled(df, raison_col)
    if existing_fill >= new_fill and existing_fill > 0:
        return df

    for idx in df.index:
        if _cell_is_empty(df.at[idx, 'raison_sociale']) and not _cell_is_empty(df.at[idx, raison_col]):
            df.at[idx, 'raison_sociale'] = df.at[idx, raison_col]
    if new_fill > existing_fill and raison_col != 'raison_sociale':
        df = df.drop(columns=[raison_col], errors='ignore')
    return df


def _is_declatvaa_filename(filename):
    if not filename:
        return False
    base = os.path.basename(str(filename)).lower().replace(' ', '')
    return 'declatvaa' in base


def _find_total_column(df):
    if df is None or df.empty:
        return None
    for col in df.columns:
        if _normalize_col(str(col)) == 'total':
            return col
    for col in df.columns:
        nc = _normalize_col(str(col))
        if nc in ('somme_total', 'somme_de_total', 'somme_de_totale'):
            return col
    return None


def _apply_declatvaa_montant_column(df):
    """DECLATVAA.xlsx : pas de montant à payer — utiliser la colonne total."""
    total_col = _find_total_column(df)
    if total_col is None:
        return df
    if 'montant' not in df.columns:
        return df.rename(columns={total_col: 'montant'})
    for idx in df.index:
        val = df.at[idx, total_col]
        if not _cell_is_empty(val):
            df.at[idx, 'montant'] = val
    return df


def _standardize_columns(df, source_filename=None):
    if _is_declatvaa_filename(source_filename):
        df = _apply_declatvaa_montant_column(df)

    rename_map = {}
    used_targets = set()
    for target, aliases in STANDARD_COLUMNS.items():
        if target in df.columns:
            if target == 'raison_sociale' and _count_col_filled(df, target) == 0:
                pass
            else:
                used_targets.add(target)
                continue
        if target == 'raison_sociale':
            best_col = None
            best_score = -1
            for col in df.columns:
                if col in rename_map or col in used_targets:
                    continue
                if _column_matches(col, aliases):
                    sc = _score_column_as_name(df, col)
                    if sc > best_score:
                        best_score = sc
                        best_col = col
            if best_col:
                rename_map[best_col] = target
                used_targets.add(target)
            continue
        for col in df.columns:
            if col in rename_map or col in used_targets:
                continue
            if _column_matches(col, aliases):
                rename_map[col] = target
                used_targets.add(target)
                break
    if rename_map:
        df = df.rename(columns=rename_map)

    if 'etat' not in df.columns:
        for col in list(df.columns):
            if col in rename_map.values():
                continue
            if col == 'etat' or col.startswith('etat_') or col.endswith('_etat'):
                df = df.rename(columns={col: 'etat'})
                break
            if col.startswith('statut') and 'fiscal' in col:
                df = df.rename(columns={col: 'etat'})
                break

    if 'montant' not in df.columns and _is_declatvaa_filename(source_filename):
        df = _apply_declatvaa_montant_column(df)

    df = _ensure_montant_column(df)
    df = _ensure_montant_paye_column(df)
    df = _ensure_raison_column(df)
    if 'date_creation' not in df.columns:
        for col in list(df.columns):
            nc = _normalize_col(str(col))
            if 'date' in nc and any(k in nc for k in ('creation', 'declar', 'depot', 'enregistrement', 'crea')):
                df = df.rename(columns={col: 'date_creation'})
                break
    df = _collapse_duplicate_columns(df)
    return df


def _cell_is_empty(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return True
    return str(val).strip() == ''


def _is_montant_a_payer_col(col):
    c = _normalize_col(str(col))
    if any(k in c for k in ('montant_paye', 'montant_paid', 'montant_verse', 'montant_recu', 'montant_percu', 'montant_encaisse')):
        return False
    if 'recu' in c and 'montant' in c:
        return False
    if 'paye' in c and 'payer' not in c and 'montant' in c:
        return False
    return c in ('montant_a_payer', 'montant_apayer', 'montant_du') or 'montant_a_payer' in c


def _is_montant_recu_col(col):
    """Colonne montant effectivement reçu / payé (≠ montant à payer / déclaré)."""
    c = _normalize_col(str(col))
    if c in (
        'montant_paye', 'montant_paid', 'montant_verse', 'montant_recu',
        'montant_percu', 'montant_encaisse',
    ):
        return True
    if 'recu' in c and 'montant' in c:
        return True
    if 'paye' in c and 'payer' not in c and 'montant' in c:
        return True
    return False


def _is_montant_declare_col(col):
    """Colonne montant déclaré / à payer (tous contribuables, payés ou non)."""
    if _is_montant_recu_col(col):
        return False
    c = _normalize_col(str(col))
    if _is_montant_a_payer_col(col):
        return True
    if c in (
        'montant', 'montant_declare', 'montant_attendu', 'montant_reference',
        'somme_totale_declaree', 'somme_declaree', 'somme',
    ):
        return True
    if 'montant' in c and any(k in c for k in ('declare', 'declar', 'attendu', 'payer', 'du')):
        return True
    if c.startswith('somme') and 'total' in c and 'declare' in c:
        return True
    return False


def _ensure_montant_column(df):
    """Phase 1 : priorité montant à payer, sinon montant générique."""
    if df is None or df.empty:
        return df

    pay_col = None
    for col in df.columns:
        if _is_montant_a_payer_col(col):
            pay_col = col
            break

    if pay_col is None:
        return df

    if 'montant' not in df.columns:
        return df.rename(columns={pay_col: 'montant'})

    if pay_col == 'montant':
        return df

    for idx in df.index:
        pay_val = df.at[idx, pay_col]
        if not _cell_is_empty(pay_val):
            df.at[idx, 'montant'] = pay_val
    return df


def _ensure_montant_paye_column(df):
    """Normalise la colonne montant reçu / payé (≠ montant à payer / déclaré)."""
    if df is None or df.empty:
        return df
    if 'montant_paye' in df.columns:
        return df
    recu_col = None
    for col in df.columns:
        if _is_montant_recu_col(col):
            recu_col = col
            break
    if recu_col:
        return df.rename(columns={recu_col: 'montant_paye'})
    return df


def _normalize_col(s: str) -> str:
    if s is None:
        return ''
    s = str(s)
    s = unicodedata.normalize('NFKD', s)
    s = s.encode('ascii', 'ignore').decode('ascii')
    s = s.lower()
    s = re.sub(r'[^a-z0-9]', '_', s)
    s = re.sub(r'_+', '_', s)
    return s.strip('_')


def _collapse_duplicate_columns(df):
    """Fusionne les colonnes homonymes (ex. deux « raison_sociale ») en gardant la 1re valeur non vide."""
    if df is None or df.empty or df.columns.is_unique:
        return df
    out = {}
    for name in dict.fromkeys(df.columns):
        subset = df.loc[:, df.columns == name]
        if subset.shape[1] == 1:
            out[name] = subset.iloc[:, 0]
        else:
            combined = subset.iloc[:, 0].astype(object).copy()
            for j in range(1, subset.shape[1]):
                col = subset.iloc[:, j]
                empty = combined.apply(_cell_is_empty)
                combined.loc[empty] = col.loc[empty]
            out[name] = combined
    return pd.DataFrame(out)


def _row_scalar(row, key):
    """Valeur scalaire d'une cellule (gère les colonnes dupliquées dans une Series pandas)."""
    if key not in row.index:
        return None
    val = row[key]
    if isinstance(val, pd.Series):
        for v in val:
            if not _cell_is_empty(v):
                return v
        return None
    return val


def _get_val(row, keys, default=None):
    for k in keys:
        val = _row_scalar(row, k)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        if isinstance(val, str):
            val = val.strip()
        if val != '':
            return val
    return default


def _parse_float(val, default=0.0):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    try:
        s = str(val).strip().replace(' ', '').replace(',', '.')
        s = re.sub(r'[^\d.\-]', '', s)
        return float(s) if s else default
    except (ValueError, TypeError):
        return default


def _parse_etat(val):
    """Retourne l'état numérique 0–3 tel que présent dans le fichier source."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    raw = str(val).strip()
    if not raw:
        return None
    try:
        etat = int(float(raw.replace(',', '.')))
        if etat in (0, 1, 2, 3):
            return etat
    except (ValueError, TypeError):
        pass
    label_map = {
        '0': 0, 'non': 0, 'nondeclaré': 0, 'nondeclare': 0, 'nondeclarant': 0,
        '1': 1, 'neant': 1, 'néant': 1,
        '2': 2, 'relicataire': 2,
        '3': 3, 'payé': 3, 'paye': 3, 'paid': 3, 'payéetdeclaré': 3,
    }
    norm = _normalize_col(raw).replace('_', '')
    if norm in label_map:
        return label_map[norm]
    return None


def _normalize_raison(val):
    if not val or (isinstance(val, float) and pd.isna(val)):
        return ''
    s = str(val).strip()
    s = re.sub(r'\s+', ' ', s)
    return s.title() if s.isupper() or s.islower() else s


GENERIC_CENTRES = {
    _normalize_key(x) for x in (
        'CIME CENTRE-EXTER', 'CENTRE-EXTER', 'CIME', 'CRIC', 'CRIC2', 'CRIC EXT',
        'CENTRE DE RATTACHEMENT', 'CFLP', 'CFPL',
    )
}


def _header_has_niu(header_cells):
    for cell in header_cells:
        nc = _normalize_col(cell)
        if nc in ('niu', 'num_niu', 'numero_niu', 'identifiant_unique', 'matricule'):
            return True
        if nc.startswith('niu_') or nc.endswith('_niu'):
            return True
    return False


def _dataframe_from_raw_with_header(raw_df, header_row):
    headers = []
    for i, val in enumerate(raw_df.iloc[header_row].tolist()):
        nc = _normalize_col(val)
        headers.append(nc if nc else f'col_{i}')
    body = raw_df.iloc[header_row + 1:].copy()
    body.columns = headers[:body.shape[1]]
    return body.dropna(how='all')


def _count_valid_niu_rows(df):
    if df is None or df.empty:
        return 0
    work = df.copy()
    norm_map = {orig: _normalize_col(orig) for orig in work.columns}
    work = work.rename(columns=norm_map)
    work = _standardize_columns(work)

    niu_col = None
    for candidate in ['niu', 'identifiant_unique', 'num_niu', 'matricule']:
        if candidate in work.columns:
            niu_col = candidate
            break
    if niu_col is None:
        for col in work.columns:
            if col == 'niu' or col.endswith('_niu') or col.startswith('niu_'):
                niu_col = col
                break
    if not niu_col:
        return 0

    count = 0
    for val in work[niu_col]:
        if pd.isna(val):
            continue
        niu = normalize_niu(val)
        if niu and is_valid_niu(niu):
            count += 1
    return count


def _score_import_sheet(df):
    """Privilégie la feuille la plus complète, pas seulement celle avec le plus de lignes."""
    niu_count = _count_valid_niu_rows(df)
    if niu_count == 0:
        return 0

    work = df.copy()
    norm_map = {orig: _normalize_col(orig) for orig in work.columns}
    work = work.rename(columns=norm_map)
    work = _standardize_columns(work)

    richness = sum(1 for col in (
        'raison_sociale', 'secteur', 'cdi', 'montant', 'lieux_dit', 'ville', 'quartier', 'regime', 'etat',
    ) if col in work.columns)

    return niu_count + richness * 5000


def _load_best_excel_sheet(xl, preview_rows=80):
    """
    Détecte la meilleure feuille via un aperçu (nrows limité),
    puis charge la feuille retenue une seule fois en entier.
    Retourne (dataframe, sheet_name, score).
    """
    best_sheet = None
    best_score = -1
    best_header_row = 0
    best_use_raw_header = False

    for sheet in xl.sheet_names:
        try:
            df_std = pd.read_excel(xl, sheet_name=sheet, dtype=str, nrows=preview_rows)
            if not df_std.empty:
                score = _score_import_sheet(df_std)
                if score > best_score:
                    best_score = score
                    best_sheet = sheet
                    best_header_row = 0
                    best_use_raw_header = False
        except Exception:
            pass

        try:
            raw = pd.read_excel(xl, sheet_name=sheet, dtype=str, header=None, nrows=preview_rows + 15)
            if raw.empty:
                continue
            for hr in range(min(15, len(raw))):
                if not _header_has_niu(raw.iloc[hr].tolist()):
                    continue
                df_hdr = _dataframe_from_raw_with_header(raw, hr)
                score = _score_import_sheet(df_hdr)
                if score > best_score:
                    best_score = score
                    best_sheet = sheet
                    best_header_row = hr
                    best_use_raw_header = True
        except Exception:
            pass

    if best_sheet is None:
        if xl.sheet_names:
            df = pd.read_excel(xl, sheet_name=xl.sheet_names[0], dtype=str)
            return df, xl.sheet_names[0], 0
        return pd.DataFrame(), None, 0

    if best_use_raw_header:
        raw_full = pd.read_excel(xl, sheet_name=best_sheet, dtype=str, header=None)
        best_df = _dataframe_from_raw_with_header(raw_full, best_header_row)
    else:
        best_df = pd.read_excel(xl, sheet_name=best_sheet, dtype=str)

    return best_df, best_sheet, best_score


def _prepare_import_dataframe(filepath_or_buffer):
    """Lit et normalise les colonnes (sans filtre NIU) — base commune upload / comptage."""
    df = read_dataframe(filepath_or_buffer)
    if df is None or df.empty:
        return df, set()
    orig_columns = list(df.columns)
    norm_map = {orig: _normalize_col(orig) for orig in orig_columns}
    df = df.rename(columns=norm_map)
    df = _standardize_columns(df)
    df = df.dropna(how='all')
    return df, set(df.columns)


def inspect_upload_file(filepath):
    """
    Une seule lecture Excel/CSV à l'upload : type, colonnes, nombre de lignes (wizard).
    Le décompte inclut toutes les lignes non vides du fichier, avant filtre NIU.
    """
    df, cols = _prepare_import_dataframe(filepath)
    if df.empty:
        return 'unknown', cols, 0
    return detect_file_type_from_cols(cols), cols, len(df)


def peek_file_columns(filepath):
    """Détection du type de fichier (colonnes normalisées)."""
    ftype, cols, _nb = inspect_upload_file(filepath)
    return ftype, cols


def count_file_data_rows(filepath):
    """Nombre de lignes de données — même logique que inspect_upload_file."""
    _ftype, _cols, nb = inspect_upload_file(filepath)
    return nb


def _resolve_cdi(row):
    cdi_raw = str(_get_val(row, [
        'cdi', 'centre_des_impots', 'centre_impots', 'centre',
        'centre_fiscal', 'centre_de_rattachement',
    ], '') or '').strip()

    direct = normalize_cdi(cdi_raw)
    if direct in get_all_cdi_labels():
        return direct

    if cdi_raw and _normalize_key(cdi_raw) not in GENERIC_CENTRES:
        inferred = infer_cdi_from_text(cdi_raw)
        if inferred:
            return inferred
        if direct:
            return direct

    for field in ['lieux_dit', 'ville', 'quartier']:
        match = infer_cdi_from_text(_get_val(row, [field], ''))
        if match:
            return match

    return direct or cdi_raw


def detect_file_type_from_cols(cols: set) -> str:
    """Détecte le type de fichier : en_ligne (référence) ou sectoriel (déclarants)."""
    from services.ca_analysis import has_ca_columns
    if has_ca_columns(cols):
        return 'ca'
    has_niu = 'niu' in cols
    has_secteur = any(k in cols for k in ('secteur',))
    has_cdi = any(k in cols for k in ('cdi', 'centre_des_impots', 'centre_impots', 'centre', 'centre_fiscal'))
    has_montant = any(k in cols for k in ('montant_attendu', 'montant', 'somme_totale_declaree', 'somme_declaree'))

    # Fichier en ligne = référence (NIU + secteur/CFLP ; montant optionnel)
    if has_niu and (has_secteur or has_cdi) and not has_montant:
        return 'en_ligne'
    if has_niu and has_montant and (has_secteur or has_cdi):
        return 'en_ligne'
    if has_secteur and has_cdi and has_niu:
        return 'en_ligne'
    # Fichiers sectoriels / consolidé déclarants : NIU + montant (sans critère référence)
    if has_niu and has_montant:
        return 'sectoriel'
    if has_niu and any(k in cols for k in ('somme_totale_declaree', 'somme_declaree', 'somme')):
        return 'sectoriel'
    if has_niu:
        return 'sectoriel'
    if any(k in cols for k in ('somme_totale_declaree', 'somme_declaree', 'somme')):
        return 'declaration'
    if any(k in cols for k in ('montant_paye',)) and any(k in cols for k in ('date_paiement',)):
        return 'paiement'
    return 'unknown'


def _patch_openpyxl_european_numbers():
    """
    openpyxl convertit les cellules numériques via _cast_number, qui fait int(value)
    sans gérer la virgule décimale (ex. taux « 19,25 ») → ValueError à la lecture.
    """
    try:
        import openpyxl.worksheet._reader as ox_reader
    except ImportError:
        return
    if getattr(ox_reader, '_fiscal_cast_number_patched', False):
        return

    _original_cast = ox_reader._cast_number

    def _cast_number(value):
        s = str(value).strip()
        if re.match(r'^-?\d+,\d+$', s):
            return float(s.replace(',', '.'))
        return _original_cast(value)

    ox_reader._cast_number = _cast_number
    ox_reader._fiscal_cast_number_patched = True


_patch_openpyxl_european_numbers()


def read_dataframe(filepath_or_buffer):
    """Lit un fichier Excel/CSV depuis un chemin ou un buffer."""
    _patch_openpyxl_european_numbers()
    if hasattr(filepath_or_buffer, 'read'):
        name = getattr(filepath_or_buffer, 'filename', '') or ''
        if name.lower().endswith('.csv'):
            return pd.read_csv(filepath_or_buffer, dtype=str)
        with pd.ExcelFile(filepath_or_buffer) as xl:
            best_df, _, score = _load_best_excel_sheet(xl)
            if best_df is not None and score > 0:
                return best_df.copy()
            if xl.sheet_names:
                return pd.read_excel(xl, sheet_name=xl.sheet_names[0], dtype=str)
            return pd.DataFrame()

    path = str(filepath_or_buffer)
    if path.lower().endswith('.csv'):
        return pd.read_csv(path, dtype=str)

    with pd.ExcelFile(path) as xl:
        best_df, _, score = _load_best_excel_sheet(xl)
        if best_df is not None and score > 0:
            return best_df.copy()
        if xl.sheet_names:
            return pd.read_excel(xl, sheet_name=xl.sheet_names[0], dtype=str)
        return pd.DataFrame()


def read_and_clean(filepath_or_buffer, dedupe=False, source_filename=None):
    """Lit un fichier Excel/CSV et applique un nettoyage automatique sans réduire le jeu de données par défaut."""
    from services.excel_pipeline import filter_valid_niu_df

    if source_filename is None and isinstance(filepath_or_buffer, str):
        source_filename = os.path.basename(filepath_or_buffer)

    df = read_dataframe(filepath_or_buffer)

    orig_columns = list(df.columns)
    norm_map = {orig: _normalize_col(orig) for orig in orig_columns}
    df = df.rename(columns=norm_map)
    df = _standardize_columns(df, source_filename=source_filename)

    niu_col = 'niu' if 'niu' in df.columns else None
    if niu_col is None:
        for col in df.columns:
            if 'niu' in col or col == 'identifiant_unique':
                df = df.rename(columns={col: 'niu'})
                niu_col = 'niu'
                break

    if niu_col:
        df = filter_valid_niu_df(df, niu_col)
        if dedupe:
            df = df.drop_duplicates(subset=[niu_col], keep='first')

    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].map(lambda x: x.strip() if isinstance(x, str) else x)

    return df, set(df.columns)


def _find_niu(row):
    return _get_val(row, ['niu', 'identifiant_unique', 'num_niu', 'matricule'], '')


def _upsert_contribuable(db_session, niu, raison=''):
    c = db_session.query(Contribuable).filter_by(niu=niu).first()
    if not c:
        c = Contribuable(niu=niu, raison=raison)
        db_session.add(c)
    elif raison and not c.raison:
        c.raison = raison
    return c


def _apply_fiscal_etat(db_session, c, etat, montant_paye=0):
    """Applique l'état fiscal et crée déclaration / paiement si nécessaire."""
    if etat is None:
        return
    old = c.etat if c.etat is not None else 0
    c.etat = etat
    if old != etat:
        db_session.add(StateHistory(niu=c.niu, old_state=old, new_state=etat))

    if montant_paye > 0:
        c.montant_paye = montant_paye

    if etat >= 2:
        existing_dec = db_session.query(Declaration).filter_by(niu=c.niu).first()
        if not existing_dec:
            db_session.add(Declaration(
                niu=c.niu,
                raison=c.raison,
                secteur=c.secteur or '',
                sous_secteur=c.sous_secteur or '',
                cdi=c.cdi or '',
                somme_totale_declaree=montant_paye or c.montant_attendu or 0,
            ))

    if etat == 3:
        existing_pay = db_session.query(Paiement).filter_by(niu=c.niu).first()
        if not existing_pay and montant_paye > 0:
            db_session.add(Paiement(niu=c.niu, montant_paye=montant_paye, date_paiement=''))


def _process_en_ligne_row(db_session, row, idx, errors):
    """Traite une ligne du fichier en ligne (base de référence)."""
    niu = _find_niu(row)
    if not niu:
        errors.append(f'Ligne {idx + 1}: NIU manquant')
        return False
    if not is_valid_niu(niu):
        errors.append(f'Ligne {idx + 1}: NIU invalide: {niu}')
        return False

    raison = _normalize_raison(_get_val(row, ['raison_sociale', 'raison', 'nom', 'nom_contribuable'], ''))
    cdi = _resolve_cdi(row)
    montant = _parse_float(_get_val(row, ['montant', 'montant_attendu', 'nombre_de_montant'], 0))

    c = _upsert_contribuable(db_session, niu, raison)
    c.raison = raison or c.raison
    c.cdi = cdi or c.cdi
    c.montant_attendu = montant
    # Secteur CIME : assigné à l'étape 5 (RECHERCHEV fichier secteurs), pas ici.
    return True


def _pick_raison_from_row(row, df_context=None):
    """Nom / raison sociale — accepte Nom, Nom contribuable, Raison sociale, etc."""
    val = _get_val(row, [
        'raison', 'raison_sociale', 'raison_social', 'raison_sociale1', 'raison_sociale2',
        'nom', 'nom_contribuable', 'nomcontribuable', 'nom_du_contribuable',
        'contribuable', 'denomination', 'libelle', 'intitule', 'designation',
        'redevable', 'nom_du_redevable', 'nom_ou_raison_sociale', 'entreprise', 'societe', 'noms',
    ], None)
    if val is not None and not _cell_is_empty(val):
        return _normalize_raison(val)

    search_df = df_context if df_context is not None else pd.DataFrame([row])
    raison_col = _find_raison_column(row.index, search_df)
    if raison_col:
        v = _row_scalar(row, raison_col)
        if not _cell_is_empty(v):
            return _normalize_raison(v)

    for col in row.index:
        nc = _normalize_col(str(col))
        if _is_raison_like_column(nc):
            v = _row_scalar(row, col)
            if not _cell_is_empty(v):
                return _normalize_raison(v)

    for col in row.index:
        nc = _normalize_col(str(col))
        if _is_non_name_column(nc):
            continue
        v = _row_scalar(row, col)
        if _looks_like_name_value(v):
            return _normalize_raison(v)
    return ''


def _pick_etat_raw_from_row(row):
    """État tel qu'il apparaît dans le fichier (ex. Payé, 2, Relicataire)."""
    val = _get_val(row, ['etat', 'etat_fiscal', 'state', 'statut', 'statut_fiscal'], None)
    if val is not None and not _cell_is_empty(val):
        return str(val).strip()
    return ''


def _pick_montant_declare_from_row(row, source_filename=None):
    """Montant à payer (priorité colonne dédiée). DECLATVAA : colonne total uniquement."""
    if _is_declatvaa_filename(source_filename):
        val = _get_val(row, ['montant', 'total'], None)
        if val is not None and not _cell_is_empty(val):
            return _parse_float(val, 0.0)
        for col in row.index:
            nc = _normalize_col(str(col))
            if nc == 'total' or nc in ('somme_total', 'somme_de_total', 'somme_de_totale'):
                v = row[col]
                if not _cell_is_empty(v):
                    return _parse_float(v, 0.0)
        return 0.0

    val = _get_val(row, [
        'montant_a_payer', 'montant_apayer', 'montant_du',
        'montant_declare', 'montant', 'montant_attendu', 'montant_reference',
        'somme_totale_declaree', 'somme_declaree', 'somme',
    ], None)
    if val is not None and not _cell_is_empty(val):
        return _parse_float(val, 0.0)
    for col in row.index:
        if not _is_montant_declare_col(col):
            continue
        v = row[col]
        if not _cell_is_empty(v):
            return _parse_float(v, 0.0)
    return 0.0


def _pick_montant_paye_from_row(row):
    """Montant reçu / payé explicite dans le fichier (colonne dédiée)."""
    val = _get_val(row, [
        'montant_paye', 'montant_paid', 'montant_verse',
        'montant_recu', 'montant_percu', 'montant_encaisse',
    ], None)
    if val is not None and not _cell_is_empty(val):
        s = str(val).strip()
        if s.upper() in ('N/A', 'NA', '-', '—', 'VIDE', 'NULL'):
            return None
        return _parse_float(val, 0.0)
    for col in row.index:
        if _is_montant_recu_col(col):
            v = row[col]
            if _cell_is_empty(v):
                continue
            s = str(v).strip()
            if s.upper() in ('N/A', 'NA', '-', '—', 'VIDE', 'NULL'):
                continue
            return _parse_float(v, 0.0)
    return None


def _row_indicates_paid(etat, etat_display):
    """True si la ligne indique un contribuable ayant payé sa déclaration."""
    if etat == 3:
        return True
    raw = _normalize_col(str(etat_display or '')).replace('_', '')
    return raw in ('3', 'paye', 'paid', 'payeetdeclare', 'declarant')


def _resolve_montant_recu_from_row(row):
    """
    Montant effectivement reçu :
    - colonne montant payé / reçu si présente ;
    - sinon montant déclaré lorsque l'état indique « Payé ».
    """
    mp = _pick_montant_paye_from_row(row)
    if mp is not None:
        return mp
    etat = _parse_etat(_get_val(row, ['etat'], None))
    etat_display = _pick_etat_raw_from_row(row)
    if not _row_indicates_paid(etat, etat_display):
        return None
    declared = _pick_montant_declare_from_row(row)
    return declared if declared > 0 else None


def _pick_montant_from_row(row):
    return _pick_montant_declare_from_row(row)


def _parse_date_creation(val):
    """Retourne (année, mois) à partir de la date de création / déclaration."""
    if _cell_is_empty(val):
        return None
    if isinstance(val, pd.Timestamp):
        return (int(val.year), int(val.month))
    if isinstance(val, datetime):
        return (val.year, val.month)
    s = str(val).strip()
    if re.fullmatch(r'\d+(\.0+)?', s):
        try:
            serial = float(s)
            if 20_000 <= serial <= 80_000:
                dt = pd.Timestamp('1899-12-30') + pd.Timedelta(days=int(serial))
                return (int(dt.year), int(dt.month))
        except (ValueError, TypeError, OverflowError):
            pass
    try:
        dt = pd.to_datetime(val, dayfirst=True, errors='coerce')
        if pd.notna(dt):
            return (int(dt.year), int(dt.month))
    except (ValueError, TypeError):
        pass
    return None


def _pick_date_creation_from_row(row):
    """Date à laquelle la déclaration a été faite (colonne date_creation / date_de_creation)."""
    val = _get_val(row, ['date_creation'], None)
    if val is not None:
        parsed = _parse_date_creation(val)
        if parsed:
            return parsed
    for col in row.index:
        nc = _normalize_col(str(col))
        if nc in STANDARD_COLUMNS['date_creation']:
            v = _row_scalar(row, col)
            if not _cell_is_empty(v):
                parsed = _parse_date_creation(v)
                if parsed:
                    return parsed
        if 'creation' in nc and nc.startswith('date'):
            v = _row_scalar(row, col)
            if not _cell_is_empty(v):
                parsed = _parse_date_creation(v)
                if parsed:
                    return parsed
    return None


def aggregate_monthly_recu_tcd_from_rows(rows):
    """
    TCD (équivalent Excel) : SOMME(montant reçu) par (année, mois) selon date_creation.
    - Lignes : mois (1–12) × année (date_creation)
    - Valeurs : montant reçu / payé (colonne dédiée, ou montant déclaré si état Payé)
    - Pas de montant « attendu » seul (relicataires / impayés exclus)
    Structure : {"2026": {"1": 123.0, "2": 456.0}, "2025": {...}}
    """
    by_year = {}
    for rec in rows:
        dt = rec.get('date_creation')
        if not dt:
            continue
        montant = rec.get('montant_paye')
        if montant is None:
            continue
        montant = float(montant)
        if montant <= 0:
            continue
        year, month = dt
        ys = str(int(year))
        try:
            ms = str(int(month))
        except (TypeError, ValueError):
            continue
        bucket = by_year.setdefault(ys, {})
        bucket[ms] = bucket.get(ms, 0.0) + montant
    return by_year


def load_monthly_recu_data(db_session):
    from services.consolidation import load_monthly_recu_dict
    return load_monthly_recu_dict(db_session)


def _extract_tcd_rows_from_dataframe(df):
    """Une ligne par ligne source : NIU, raison, état (0–3), montant — valeurs lues dans le fichier."""
    if df is None or df.empty or 'niu' not in df.columns:
        return []
    df = _ensure_raison_column(df.copy())
    df = _collapse_duplicate_columns(df)
    rows = []
    for _, row in df.iterrows():
        niu = normalize_niu(_get_val(row, ['niu'], ''))
        if not niu or not is_valid_niu(niu):
            continue
        etat = _parse_etat(_get_val(row, ['etat'], None))
        etat_display = _pick_etat_raw_from_row(row)
        rows.append({
            'niu': niu,
            'raison': _pick_raison_from_row(row, df),
            'etat': etat,
            'etat_display': etat_display,
            'montant': _pick_montant_declare_from_row(row),
            'montant_recu': _pick_montant_paye_from_row(row),
            'montant_paye': _resolve_montant_recu_from_row(row),
            'date_creation': _pick_date_creation_from_row(row),
        })
    return rows


def pivot_tcd_from_rows(rows):
    """
    Tableau croisé dynamique (équivalent Excel sur tous les fichiers empilés) :
    - Lignes : NIU
    - Valeurs : SOMME(Montant déclaré), SOMME(Montant reçu)
    - Nom / État : premières valeurs non vides du fichier
    """
    consolidated = {}
    for rec in rows:
        niu = rec['niu']
        if niu not in consolidated:
            consolidated[niu] = {
                'raison': rec.get('raison') or '',
                'etat': rec.get('etat'),
                'etat_display': rec.get('etat_display') or '',
                'montant_declare': float(rec.get('montant') or 0),
                'montant_paye': None,
                '_paye_parts': [],
            }
        else:
            consolidated[niu]['montant_declare'] += float(rec.get('montant') or 0)
            new_raison = rec.get('raison') or ''
            if new_raison and (
                not consolidated[niu]['raison']
                or len(new_raison) > len(consolidated[niu]['raison'])
            ):
                consolidated[niu]['raison'] = new_raison
            if not consolidated[niu]['etat_display'] and rec.get('etat_display'):
                consolidated[niu]['etat_display'] = rec['etat_display']
            if consolidated[niu]['etat'] is None and rec.get('etat') is not None:
                consolidated[niu]['etat'] = rec['etat']
        mp = rec.get('montant_paye')
        if mp is not None:
            consolidated[niu]['_paye_parts'].append(float(mp))

    for data in consolidated.values():
        parts = data.pop('_paye_parts', [])
        if parts:
            data['montant_paye'] = sum(parts)
    return consolidated


def aggregate_tcd_from_df(df):
    """TCD vectorisé sur un fichier sectoriel."""
    from services.excel_pipeline import (
        build_sector_dataframe, pivot_tcd_from_dataframe, sector_df_to_row_dicts,
    )
    sector_df = build_sector_dataframe(df)
    if sector_df.empty:
        return {}
    return pivot_tcd_from_dataframe(sector_df)


def process_sector_file_vectorized(df, source_filename=''):
    """Pipeline vectorisé complet pour un fichier sectoriel → sector_df, consolidated, monthly, rows."""
    from services.excel_pipeline import (
        aggregate_monthly_recu_from_dataframe,
        build_sector_dataframe,
        pivot_tcd_from_dataframe,
        sector_df_to_row_dicts,
    )
    sector_raw = extract_sector_columns(df)
    if sector_raw is None or sector_raw.empty or 'niu' not in sector_raw.columns:
        return None
    nb_lignes_brutes = len(sector_raw.dropna(how='all'))

    sector_df = build_sector_dataframe(df, source_filename=source_filename)
    if sector_df.empty:
        return None
    consolidated = pivot_tcd_from_dataframe(sector_df)
    monthly = aggregate_monthly_recu_from_dataframe(sector_df)
    rows = sector_df_to_row_dicts(sector_df)
    return {
        'sector_df': sector_df,
        'consolidated': consolidated,
        'monthly_recu': monthly,
        'rows': rows,
        'nb_lignes': len(sector_df),
        'nb_lignes_brutes': nb_lignes_brutes,
    }


def extract_sector_columns(df):
    """Ne conserve que NIU, nom/raison sociale, état et montant (ignore les autres colonnes)."""
    if df is None or df.empty:
        return df
    df = _ensure_raison_column(df.copy())
    rename = {}
    if 'raison' not in df.columns:
        if 'raison_sociale' in df.columns:
            rename['raison_sociale'] = 'raison'
        else:
            raison_col = _find_raison_column(df.columns, df)
            if raison_col:
                rename[raison_col] = 'raison'
    if rename:
        df = df.rename(columns=rename)
    keep = []
    for col in ('niu', 'raison', 'etat', 'montant', 'montant_paye', 'date_creation'):
        if col in df.columns:
            keep.append(col)
    if 'niu' not in keep:
        return df
    return df[keep].copy()


def _declatvaa_file_priority(filename):
    """
    Priorité DECLATVAA lors du dédoublonnage entre fichiers :
    snapshot mensuel (ex. DECLATVAA JUIN) > cumul Janv-Juin (2025, 2026…).
    """
    if not filename:
        return 0
    base = os.path.basename(str(filename)).lower().replace(' ', '').replace('_', '').replace('-', '')
    if 'declatvaa' not in base:
        return 0
    if 'janv' in base or 'semestre' in base or '1sem' in base:
        prio = 100
        if '2026' in base:
            prio += 20
        elif '2025' in base:
            prio += 10
        return prio
    return 1000


def _consolidated_entry(data, source_filename=None):
    entry = {
        'raison': data.get('raison', ''),
        'montant_declare': float(data.get('montant_declare', 0) or 0),
        'montant_paye': data.get('montant_paye'),
        'etat': data.get('etat'),
        'etat_display': data.get('etat_display', ''),
    }
    if source_filename and _is_declatvaa_filename(source_filename):
        entry['_declatvaa_prio'] = _declatvaa_file_priority(source_filename)
        entry['_declatvaa_source'] = os.path.basename(str(source_filename))
    return entry


def merge_declatvaa_consolidated(target, source, source_filename):
    """
    Fusionne des TCD DECLATVAA : un NIU ne doit pas cumuler Janv-Juin + JUIN.
    On conserve la source la plus prioritaire (photo du mois, pas le cumul période).
    """
    prio = _declatvaa_file_priority(source_filename)
    for niu, data in source.items():
        if niu not in target:
            target[niu] = _consolidated_entry(data, source_filename)
            continue
        existing_prio = target[niu].get('_declatvaa_prio', 0)
        if prio >= existing_prio:
            target[niu] = _consolidated_entry(data, source_filename)


def _strip_declatvaa_meta(consolidated):
    """Retire uniquement les métadonnées internes DECLATVAA."""
    for data in consolidated.values():
        data.pop('_declatvaa_prio', None)
        data.pop('_declatvaa_source', None)


def _strip_etat_for_vlookup(consolidated):
    """RECHERCHEV phase 2 : lookup sur NIU + montant uniquement (pas la colonne État)."""
    for data in consolidated.values():
        data.pop('etat', None)
        data.pop('etat_display', None)


def _strip_consolidated_meta(consolidated):
    """Alias — conserve l'état source pour aperçu / export complet."""
    _strip_declatvaa_meta(consolidated)


def merge_phase1_consolidated_parts(target, sector_parts=None, declatvaa_parts=None):
    """Fusionne les TCD intermédiaires par fichier selon le processus métier :
    - les fichiers DECLATVAA conservent la photo mensuelle la plus prioritaire ;
    - les autres fichiers sont agrégés par NIU sans écraser les infos déjà conservées.
    """
    sector_parts = sector_parts or []
    declatvaa_parts = declatvaa_parts or []

    ordered_declatvaa = sorted(
        declatvaa_parts,
        key=lambda item: _declatvaa_file_priority(item[0]) if item else 0,
        reverse=True,
    )
    for source_filename, source in ordered_declatvaa:
        if not source:
            continue
        merge_declatvaa_consolidated(target, source, source_filename)

    for source in sector_parts:
        if not source:
            continue
        merge_consolidated(target, source)

    _strip_consolidated_meta(target)
    return target


def merge_consolidated(target, source):
    """Fusionne deux résultats TCD sectoriels (somme des montants, conserve les infos déjà renseignées)."""
    for niu, data in source.items():
        if niu not in target:
            target[niu] = {
                'raison': data.get('raison', ''),
                'montant_declare': data.get('montant_declare', 0.0),
                'montant_paye': data.get('montant_paye'),
                'etat': data.get('etat'),
                'etat_display': data.get('etat_display', ''),
            }
        else:
            target[niu]['montant_declare'] += data.get('montant_declare', 0.0)
            src_paye = data.get('montant_paye')
            if src_paye is not None:
                prev = target[niu].get('montant_paye')
                target[niu]['montant_paye'] = src_paye if prev is None else prev + src_paye
            new_raison = data.get('raison') or ''
            if new_raison and (not target[niu].get('raison') or len(new_raison) > len(target[niu]['raison'])):
                target[niu]['raison'] = new_raison
            if not target[niu].get('etat_display') and data.get('etat_display'):
                target[niu]['etat_display'] = data['etat_display']
            src_etat = data.get('etat')
            if src_etat is not None:
                prev = target[niu].get('etat')
                if prev is None or int(src_etat) > int(prev):
                    target[niu]['etat'] = src_etat


def apply_vlookup_classification(db_session, reference_nius, consolidated):
    """
    RECHERCHEV : fichier en ligne vs consolidé (NIU + montant déclaré + montant payé).
    #N/A → défaillant · 0–10 → néant · >10 sans paiement → relicataire · >10 payé → déclarant.
    """
    if not reference_nius:
        return {'defaillants': 0, 'neants': 0, 'relicataires': 0, 'declarants': 0}

    stats = {'defaillants': 0, 'neants': 0, 'relicataires': 0, 'declarants': 0}

    for niu in reference_nius:
        c = db_session.query(Contribuable).filter_by(niu=niu).first()
        if not c:
            c = Contribuable(niu=niu)
            db_session.add(c)

        old = c.etat if c.etat is not None else ETAT_DEFAILLANT
        decl = consolidated.get(niu)

        if decl is None:
            c.etat = ETAT_DEFAILLANT
            c.montant_declare = 0.0
            c.montant_paye = None
            stats['defaillants'] += 1
        else:
            montant_declare = float(decl.get('montant_declare', 0) or 0)
            montant_paye = decl.get('montant_paye')
            c.montant_declare = montant_declare
            if decl.get('raison'):
                c.raison = decl['raison'] or c.raison
            if montant_paye is not None:
                try:
                    c.montant_paye = float(montant_paye)
                except (TypeError, ValueError):
                    pass
            else:
                c.montant_paye = None
            c.etat = classify_from_declaration(
                montant_declare, montant_paye=c.montant_paye, found_in_consolidated=True,
            )
            if c.etat == ETAT_NEANT:
                stats['neants'] += 1
            elif c.etat == ETAT_RELICATAIRE:
                stats['relicataires'] += 1
            elif c.etat == ETAT_DECLARANT:
                stats['declarants'] += 1

        if old != c.etat:
            db_session.add(StateHistory(niu=c.niu, old_state=old, new_state=c.etat))

    return stats


def _process_combined_row(db_session, row, idx, errors):
    """Fichier mixte traité comme référence en ligne (État ignoré pour la RECHERCHEV)."""
    return _process_en_ligne_row(db_session, row, idx, errors)


def _process_declarant_row(db_session, row, idx, errors):
    """Traite une ligne du fichier des contribuables ayant déclaré."""
    niu = _find_niu(row)
    if not niu:
        errors.append(f'Ligne {idx + 1}: NIU manquant')
        return False
    if not is_valid_niu(niu):
        errors.append(f'Ligne {idx + 1}: NIU invalide: {niu}')
        return False

    raison = _normalize_raison(_get_val(row, ['raison_sociale', 'raison', 'nom', 'nom_contribuable'], ''))
    etat = _parse_etat(_get_val(row, ['etat', 'etat_fiscal', 'state'], None))
    montant_paye = _parse_float(_get_val(row, ['montant_paye', 'montant_paye', 'montant'], 0))
    if etat == 3 and montant_paye == 0:
        montant_paye = _parse_float(_get_val(row, ['montant_attendu'], 0))

    c = _upsert_contribuable(db_session, niu, raison)
    c.raison = raison or c.raison
    if etat is not None:
        _apply_fiscal_etat(db_session, c, etat, montant_paye)
    return True


def _process_legacy_row(db_session, row, idx, ftype, cols, errors):
    """Compatibilité avec les anciens formats de fichiers."""
    niu = _find_niu(row)
    if not niu or not is_valid_niu(niu):
        return False

    raison = _normalize_raison(_get_val(row, ['raison_sociale', 'raison', 'nom'], ''))
    c = _upsert_contribuable(db_session, niu, raison)

    if ftype == 'declaration':
        declared = _parse_float(_get_val(row, ['somme_totale_declaree', 'somme_declaree', 'somme'], 0))
        secteur = str(_get_val(row, ['secteur'], '') or '')
        sous = str(_get_val(row, ['sous_secteur', 'soussecteur'], '') or '')
        cdi = normalize_cdi(_get_val(row, ['centre_des_impots', 'cdi', 'centre', 'centre_fiscal'], ''))
        db_session.add(Declaration(
            niu=niu, raison=raison, secteur=secteur, sous_secteur=sous,
            cdi=cdi, somme_totale_declaree=declared,
        ))
        c.secteur = secteur or c.secteur
        c.sous_secteur = sous or c.sous_secteur
        c.cdi = cdi or c.cdi
        c.montant_attendu = declared
    elif ftype == 'paiement':
        montant = _parse_float(_get_val(row, ['montant_paye', 'montant'], 0))
        date_p = str(_get_val(row, ['date_paiement', 'date'], '') or '')
        db_session.add(Paiement(niu=niu, montant_paye=montant, date_paiement=date_p))
        c.montant_paye = montant
    elif ftype == 'contribuable':
        etat = _parse_etat(_get_val(row, ['etat_fiscal', 'etat'], None))
        montant = _parse_float(_get_val(row, ['montant_attendu', 'montant'], 0))
        if etat is not None:
            c.etat = etat
        c.montant_attendu = montant
    return True


def run_comparison(db_session, declarants_niu=None, reference_niu=None):
    """Alias rétrocompatibilité — utiliser apply_vlookup_classification."""
    consolidated = {}
    if declarants_niu:
        for niu in declarants_niu:
            c = db_session.query(Contribuable).filter_by(niu=niu).first()
            if c:
                consolidated[niu] = {
                    'raison': c.raison or '',
                    'montant_declare': c.montant_declare or c.montant_paye or 0,
                }
    return apply_vlookup_classification(db_session, reference_niu, consolidated)


def _recompute_states(db_session):
    """Désactivé — la classification est entièrement gérée par RECHERCHEV."""
    return


def process_file(
    db_session, filepath: str, user: str = 'admin',
    reference_nius=None, consolidated=None,
) -> dict:
    errors = []
    try:
        df_full, cols = read_and_clean(filepath, dedupe=False)
        ftype = detect_file_type_from_cols(cols)
    except Exception as e:
        return {'success': False, 'error': str(e), 'nius': set(), 'file_type': 'unknown'}

    nb = 0
    processed_nius = set()

    if ftype == 'en_ligne' or (ftype == 'sectoriel' and 'montant' not in cols):
        df_ref = df_full.drop_duplicates(subset=['niu'], keep='first') if 'niu' in df_full.columns else df_full
        for idx, row in df_ref.iterrows():
            try:
                niu = _find_niu(row)
                ok = _process_en_ligne_row(db_session, row, idx, errors)
                if ok and niu:
                    processed_nius.add(niu)
                    nb += 1
            except Exception as e:
                errors.append(f'Ligne {idx + 1}: {e}')
        if reference_nius is not None:
            reference_nius.update(processed_nius)

    elif ftype in ('sectoriel', 'declarant', 'combined', 'declaration', 'unknown'):
        df_sector = extract_sector_columns(df_full)
        agg = aggregate_tcd_from_df(df_sector)
        if consolidated is not None:
            merge_consolidated(consolidated, agg)
        nb = len(agg)
        processed_nius = set(agg.keys())
        if ftype == 'unknown' and not agg:
            errors.append('Aucun NIU valide agrégé — vérifiez les colonnes NIU et montant.')
    else:
        df, _ = read_and_clean(filepath, dedupe=True)
        for idx, row in df.iterrows():
            try:
                ok = _process_legacy_row(db_session, row, idx, ftype, cols, errors)
                niu = _find_niu(row)
                if ok and niu:
                    processed_nius.add(niu)
                    nb += 1
            except Exception as e:
                errors.append(f'Ligne {idx + 1}: {e}')

    ih = ImportHistory(
        filename=os.path.basename(filepath),
        user=user,
        nb_lignes=nb,
        file_type=ftype,
        status='traite',
        errors=';'.join(errors[:50]),
    )
    db_session.add(ih)
    db_session.commit()

    return {
        'success': True,
        'file_type': ftype,
        'rows': nb,
        'errors': errors,
        'nius': processed_nius,
    }


def _format_etat_display_for_preview(data):
    """Libellé État pour aperçu / export consolidé (valeur fichier source)."""
    from fiscal_constants import ETAT_LABELS
    etat_display = (data.get('etat_display') or '').strip()
    if etat_display:
        return etat_display
    etat = data.get('etat')
    if etat is None:
        return ''
    try:
        n = int(etat)
        if n in ETAT_LABELS:
            return str(n)
    except (TypeError, ValueError):
        pass
    return str(etat)


def _consolidated_rows_for_export(consolidated):
    """Lignes Excel Phase 1 — NIU, Nom/Raison sociale, Etat, Montant à payer."""
    rows = []
    for niu in sorted(consolidated.keys()):
        data = consolidated[niu]
        rows.append({
            'NIU': niu,
            'Nom/Raison sociale': data.get('raison', ''),
            'Etat': _format_etat_display_for_preview(data),
            'Montant à payer': round(float(data.get('montant_declare', 0) or 0), 2),
        })
    return rows


def _format_fcfa(amount):
    return f"{int(round(float(amount or 0))):,}".replace(',', ' ')


def load_consolidated_meta(db_session=None, db=None):
    session = db_session if db_session is not None else db
    if session is None:
        return None
    from services.consolidation import load_consolidated_meta as _load_meta_db
    return _load_meta_db(session)


def build_phase1_notification(controls):
    nb_files = controls.get('nb_fichiers', 0)
    msg = (
        f"Consolidation terminée — {nb_files} fichier(s) · "
        f"{controls['nb_contribuables']} contribuable(s) · "
        f"Montant à payer : {_format_fcfa(controls['total_declare'])} FCFA"
    )
    annees = controls.get('annees_recu') or []
    if annees:
        msg += f" · Graphique recettes : {', '.join(str(a) for a in annees)}"
    elif controls.get('nb_lignes_recu_datees', 0) == 0:
        msg += " · Graphique mensuel : vérifiez les colonnes date de création et montant reçu / payé"
    elif controls.get('nb_lignes_sans_date', 0):
        msg += " · Colonne date de création absente sur certaines lignes"
    return msg


def save_consolidated_artifacts(consolidated, controls=None, db_session=None, all_rows=None,
                                monthly_recu=None, user='admin', source_filenames=None, **_kwargs):
    """Persiste la consolidation en SQLite (data.db)."""
    if db_session is None:
        raise ValueError('db_session requis — la consolidation est persistée en base SQLite.')

    from models import Contribuable
    from services.en_ligne_store import clear_en_ligne_artifacts
    from services.sous_secteur_ref import clear_sous_secteur_ref
    # Nouvelle consolidation → invalider la phase 2 (évite de réutiliser d'anciens totaux)
    db_session.query(Contribuable).delete()
    clear_en_ligne_artifacts(db_session, commit=False)
    clear_sous_secteur_ref(db_session, commit=False)
    db_session.flush()

    from services.consolidation import save_consolidation
    save_consolidation(
        db_session,
        consolidated,
        all_rows or [],
        controls or {},
        monthly_recu or {},
        user=user,
        source_filenames=source_filenames,
    )
    return len(consolidated)


def load_consolidated_dict(db_session):
    """Charge le consolidé depuis SQLite."""
    from services.consolidation import load_consolidated_dict as _load
    return _load(db_session)


def consolidated_is_ready(db_session):
    from services.consolidation import consolidated_is_ready as _ready_db
    return _ready_db(db_session)


def clear_consolidated_artifacts(db_session):
    from services.consolidation import clear_consolidation
    from services.en_ligne_store import clear_en_ligne_artifacts
    clear_consolidation(db_session)
    clear_en_ligne_artifacts(db_session, commit=False)
    db_session.commit()


def get_consolidated_preview(limit=100, db_session=None):
    if db_session is None:
        return [], 0
    consolidated = load_consolidated_dict(db_session)
    rows = _consolidated_rows_for_export(consolidated)
    return rows[:limit], len(rows)


def run_phase1_consolidation(filepaths, user='admin', db_session=None):
    """
    PHASE 1 — Lecture unique par fichier, pipeline vectorisé, persistance SQLite.
    """
    from services.excel_pipeline import aggregate_monthly_recu_from_dataframe

    all_rows = []
    errors = []
    files_processed = 0
    lines_raw = 0
    declatvaa_candidates = []
    sector_consolidated_parts = []

    for fp in filepaths:
        try:
            df, cols = read_and_clean(fp, dedupe=False)
            ftype = detect_file_type_from_cols(cols)
            if ftype == 'en_ligne':
                errors.append(f'{os.path.basename(fp)} : fichier en ligne — étape 2 uniquement.')
                continue

            basename = os.path.basename(fp)
            result = process_sector_file_vectorized(df, source_filename=basename)
            if result is None:
                errors.append(f'{basename} : colonnes NIU / montant introuvables ou aucune ligne valide.')
                continue

            lines_raw += result.get('nb_lignes_brutes', result['nb_lignes'])
            all_rows.extend(result['rows'])
            if _is_declatvaa_filename(basename):
                declatvaa_candidates.append((basename, result['consolidated']))
            else:
                sector_consolidated_parts.append(result['consolidated'])
            files_processed += 1
        except Exception as e:
            errors.append(f'{os.path.basename(fp)} : {e}')

    if declatvaa_candidates:
        if len(declatvaa_candidates) > 1:
            names = [name for name, _ in declatvaa_candidates]
            errors.append(
                f'DECLATVAA : sélection de la photo mensuelle la plus prioritaire parmi {", ".join(names)}.'
            )

    consolidated = merge_phase1_consolidated_parts(
        {},
        sector_parts=sector_consolidated_parts,
        declatvaa_parts=declatvaa_candidates,
    )

    if not all_rows:
        return {
            'success': False,
            'error': 'Aucun contribuable consolidé. Vérifiez vos fichiers sectoriels.',
            'errors': errors,
            'nb_contribuables': 0,
            'files_processed': files_processed,
            'controls': None,
        }

    monthly_recu = aggregate_monthly_recu_tcd_from_rows(all_rows)

    total_avant = sum(float(r.get('montant') or 0) for r in all_rows)
    total_recu_avant = sum(float(r.get('montant_paye') or 0) for r in all_rows if r.get('montant_paye') is not None)
    total_apres = sum(float(d.get('montant_declare', 0) or 0) for d in consolidated.values())
    total_recu_apres = sum(
        float(d.get('montant_paye') or 0) for d in consolidated.values() if d.get('montant_paye') is not None
    )

    controls = {
        'nb_fichiers': files_processed,
        'nb_lignes': len(all_rows),
        'nb_lignes_brutes': lines_raw,
        'nb_contribuables': len(consolidated),
        'total_avant': total_avant,
        'total_apres': total_apres,
        'total_declare': total_apres,
        'total_recu': total_recu_apres,
        'total_recu_avant': total_recu_avant,
    }

    with_date = sum(1 for r in all_rows if r.get('date_creation'))
    with_recu_date = sum(
        1 for r in all_rows
        if r.get('date_creation') and r.get('montant_paye') is not None and float(r.get('montant_paye') or 0) > 0
    )
    controls['nb_lignes_avec_date'] = with_date
    controls['nb_lignes_sans_date'] = len(all_rows) - with_date
    controls['nb_lignes_recu_datees'] = with_recu_date
    controls['nb_mois_recu'] = sum(len(v) for v in monthly_recu.values())
    controls['annees_recu'] = sorted(monthly_recu.keys())
    controls['source_filenames'] = [os.path.basename(p) for p in filepaths]

    nb = save_consolidated_artifacts(
        consolidated,
        controls=controls,
        db_session=db_session,
        all_rows=all_rows,
        monthly_recu=monthly_recu,
        user=user,
        source_filenames=[os.path.basename(p) for p in filepaths],
    )
    return {
        'success': True,
        'nb_contribuables': nb,
        'files_processed': files_processed,
        'errors': errors,
        'xlsx_path': 'fichier_consolide.xlsx',
        'controls': controls,
        'notification': build_phase1_notification(controls),
    }


def run_phase2_vlookup(db_session, en_ligne_filepaths, user='admin'):
    """
    PHASE 2 — RECHERCHEV : fichier en ligne (référence) vs consolidé (sans État).
    #N/A → défaillant · 0–10 → néant · >10 sans paiement → relicataire · >10 payé → déclarant.
    """
    from models import Contribuable
    from services.en_ligne_store import persist_en_ligne_files
    from services.secteur_cime import clear_secteur_cime_catalog
    from services.sous_secteur_ref import clear_sous_secteur_ref

    if not consolidated_is_ready(db_session):
        return {
            'success': False,
            'error': 'Phase 1 requise : lancez d\'abord la consolidation des fichiers sectoriels.',
        }

    consolidated = load_consolidated_dict(db_session)
    if not consolidated:
        return {'success': False, 'error': 'Données consolidées introuvables ou vides.'}
    # Lookup RECHERCHEV : montant déclaré uniquement (ignore l'état source en base)
    _strip_etat_for_vlookup(consolidated)

    # Conserver le fichier en ligne tel quel (modèle NHR) pour l'export
    persist_en_ligne_files(db_session, en_ligne_filepaths)
    clear_secteur_cime_catalog(db_session, commit=False)
    clear_sous_secteur_ref(db_session, commit=False)

    # Recalcul complet : seuls les NIU du fichier en ligne courant comptent
    db_session.query(Contribuable).delete()
    db_session.flush()

    reference_niu = set()
    results = []
    for fp in en_ligne_filepaths:
        res = process_file(db_session, fp, user=user, reference_nius=reference_niu)
        results.append(res)

    if not reference_niu:
        return {
            'success': False,
            'error': 'Aucun NIU valide dans le fichier en ligne.',
            'results': results,
        }

    vlookup_stats = apply_vlookup_classification(db_session, reference_niu, consolidated)
    db_session.commit()

    return {
        'success': True,
        'vlookup': vlookup_stats,
        'reference_count': len(reference_niu),
        'consolidated_count': len(consolidated),
        'results': results,
    }


def _consolidated_rows_for_export_sans_etat(consolidated):
    """Lignes consolidées sans colonne État (TCD métier Excel)."""
    rows = []
    for niu in sorted(consolidated.keys()):
        data = consolidated[niu]
        rows.append({
            'NIU': niu,
            'Nom/Raison sociale': data.get('raison', ''),
            'Montant à payer': round(float(data.get('montant_declare', 0) or 0), 2),
        })
    return rows


def _has_sector_lookup_column(cols):
    """Fichier secteurs : colonne Secteur CIME uniquement (pas activité / secteur métier)."""
    cols = set(cols or [])
    if 'secteur_cime' in cols:
        return True
    return any('cime' in str(c) or 'sim' in str(c) for c in cols)


def _pick_sector_cime_from_row(row):
    """Lit uniquement la colonne Secteur CIME — jamais la colonne activité/secteur générique."""
    val = _get_val(row, ['secteur_cime'], None)
    if val is not None and not _cell_is_empty(val):
        return str(val).strip()
    for col in row.index:
        nc = _normalize_col(str(col))
        if nc == 'secteur_cime' or 'secteur_cime' in nc or nc in ('secteur_sim', 'secteurs_cime'):
            v = _row_scalar(row, col)
            if not _cell_is_empty(v):
                return str(v).strip()
        if 'cime' in nc and 'secteur' in nc and 'sous' not in nc:
            v = _row_scalar(row, col)
            if not _cell_is_empty(v):
                return str(v).strip()
    return ''


def _pick_sous_secteur_from_row(row):
    """Lit uniquement la colonne Sous secteur du fichier secteurs (jamais Secteur / activité)."""
    explicit = ('sous_secteur', 'soussecteur', 'sous_secteur_activite')
    val = _get_val(row, list(explicit), None)
    if val is not None and not _cell_is_empty(val):
        return str(val).strip()
    for col in row.index:
        nc = _normalize_col(str(col))
        if nc in explicit:
            v = _row_scalar(row, col)
            if not _cell_is_empty(v):
                return str(v).strip()
        # Colonnes du type « sous_secteur_* » ou « soussecteur_* » uniquement
        if nc.startswith('sous_secteur_') or nc.startswith('soussecteur_'):
            v = _row_scalar(row, col)
            if not _cell_is_empty(v):
                return str(v).strip()
    return ''


def run_phase3_sector_lookup(db_session, filepaths, user='admin'):
    """
    PHASE 3 — RECHERCHEV NIU → Secteur CIME (fichier secteurs).
    Uniquement les libellés présents dans ce fichier apparaissent au TCD final.
    """
    from models import Contribuable
    from services.secteur_cime import save_secteur_cime_catalog, canonicalize_secteur_cime

    errors = []
    updated = 0
    not_found = 0
    rows_read = 0
    niu_to_secteur = {}
    niu_to_sous_secteur = {}
    catalog_labels = []

    for fp in filepaths:
        try:
            df, cols = read_and_clean(fp)
            cols_set = set(cols or [])
            if 'niu' not in cols_set:
                errors.append(f'{os.path.basename(fp)} : colonne NIU manquante.')
                continue
            if not _has_sector_lookup_column(cols_set):
                errors.append(
                    f'{os.path.basename(fp)} : colonne « Secteur CIME » (ou secteur) manquante.'
                )
                continue

            for _, row in df.iterrows():
                niu = _find_niu(row)
                if not niu or not is_valid_niu(niu):
                    continue
                rows_read += 1
                secteur_raw = _pick_sector_cime_from_row(row)
                secteur = canonicalize_secteur_cime(secteur_raw)
                if secteur:
                    niu_to_secteur[niu] = secteur
                    catalog_labels.append(secteur)
                sous = _pick_sous_secteur_from_row(row)
                if sous:
                    niu_to_sous_secteur[niu] = sous
        except Exception as e:
            errors.append(f'{os.path.basename(fp)} : {e}')

    if rows_read == 0 and errors:
        return {'success': False, 'updated': 0, 'not_found': not_found, 'errors': errors}

    if not niu_to_secteur:
        return {
            'success': False,
            'updated': 0,
            'not_found': 0,
            'errors': errors + ['Aucune ligne NIU + Secteur CIME valide dans le fichier secteurs.'],
        }

    catalog = save_secteur_cime_catalog(db_session, catalog_labels, commit=False)
    allowed = {label.upper(): label for label in catalog}

    from services.en_ligne_store import mark_sectors_applied
    from services.sous_secteur_ref import save_sous_secteur_ref

    save_sous_secteur_ref(db_session, niu_to_sous_secteur, niu_to_secteur, commit=False)

    for c in db_session.query(Contribuable).all():
        raw = niu_to_secteur.get(c.niu)
        if not raw:
            c.secteur = None
            not_found += 1
        else:
            canonical = canonicalize_secteur_cime(raw) or allowed.get(str(raw).strip().upper())
            if not canonical:
                c.secteur = None
                not_found += 1
            else:
                c.secteur = canonical
                updated += 1
        sous = niu_to_sous_secteur.get(c.niu)
        c.sous_secteur = sous.strip() if sous else None

    mark_sectors_applied(db_session)

    db_session.commit()
    return {
        'success': True,
        'updated': updated,
        'not_found': not_found,
        'rows_read': rows_read,
        'catalog_size': len(catalog),
        'errors': errors,
    }
