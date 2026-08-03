"""
Pipeline vectorisé Phase 1 — extraction sectorielle, TCD NIU, TCD mensuel recettes.
"""
import pandas as pd

from fiscal_constants import ETAT_DECLARANT
from niu import NIU_REGEX


def safe_int(val, default=None):
    """Convertit une valeur utilisateur en int (accepte les décimaux FR « 19,25 »)."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    try:
        if isinstance(val, str):
            s = val.strip().replace('\u00a0', '').replace(' ', '')
            if not s:
                return default
            return int(float(s.replace(',', '.')))
        if isinstance(val, (int, float)):
            return int(val)
        return int(float(str(val).replace(',', '.')))
    except (TypeError, ValueError, OverflowError):
        return default

_PAID_ETAT_TEXT = frozenset({
    '3', 'paye', 'paid', 'payeetdeclare', 'declarant',
})
_NA_VALUES = frozenset({'N/A', 'NA', '-', '—', 'VIDE', 'NULL', ''})


def parse_float_series(series):
    """Convertit une Series en montants float (vectorisé)."""
    if series is None:
        return pd.Series(dtype=float)
    s = series.fillna('').astype(str).str.strip()
    s = s.str.replace('\u00a0', '', regex=False).str.replace(' ', '', regex=False)
    s = s.str.replace(',', '.', regex=False)
    s = s.str.replace(r'[^\d.\-]', '', regex=True)
    return pd.to_numeric(s, errors='coerce').fillna(0.0)


def normalize_niu_series(series):
    s = series.fillna('').astype(str).str.strip().str.upper()
    return s.str.replace(' ', '', regex=False)


def filter_valid_niu_df(df, niu_col='niu'):
    if df.empty or niu_col not in df.columns:
        return df.iloc[0:0].copy()
    out = df.copy()
    out[niu_col] = normalize_niu_series(out[niu_col])
    out = out[out[niu_col].astype(str).str.len() > 0]
    pattern = NIU_REGEX.pattern
    out = out[out[niu_col].str.match(pattern, na=False)]
    return out


def parse_date_creation_series(series):
    """Retourne (year_series, month_series) alignées sur l'index."""
    if series is None:
        empty = pd.Series(dtype='Int64')
        return empty, empty
    years = pd.Series([pd.NA] * len(series), index=series.index, dtype='Int64')
    months = pd.Series([pd.NA] * len(series), index=series.index, dtype='Int64')

    dt = pd.to_datetime(series, dayfirst=True, errors='coerce')
    valid = dt.notna()
    years.loc[valid] = dt.loc[valid].dt.year.astype(int)
    months.loc[valid] = dt.loc[valid].dt.month.astype(int)

    cleaned = series.fillna('').astype(str).str.strip().str.replace('\u00a0', '', regex=False)
    cleaned = cleaned.str.replace(',', '.', regex=False)
    numeric = pd.to_numeric(cleaned, errors='coerce')
    num_mask = numeric.notna() & (numeric >= 20_000) & (numeric <= 80_000) & years.isna()
    if num_mask.any():
        excel_dt = pd.Timestamp('1899-12-30') + pd.to_timedelta(numeric.loc[num_mask].astype(int), unit='D')
        years.loc[num_mask] = excel_dt.dt.year.astype(int)
        months.loc[num_mask] = excel_dt.dt.month.astype(int)

    return years, months


def _paid_mask(df):
    """Masque vectorisé : contribuable considéré comme ayant payé."""
    mask = pd.Series(False, index=df.index)
    if 'etat' not in df.columns:
        return mask
    raw = df['etat'].fillna('').astype(str).str.strip()
    norm = raw.str.lower().str.replace('_', '', regex=False).str.replace(' ', '', regex=False)
    mask = mask | norm.isin(_PAID_ETAT_TEXT)
    etat_num = pd.to_numeric(raw.str.replace(',', '.', regex=False), errors='coerce')
    mask = mask | (etat_num == ETAT_DECLARANT) | (etat_num == 3)
    return mask


def resolve_montant_recu_series(df):
    """Montant reçu : colonne payée, sinon montant déclaré si état = payé."""
    declared = parse_float_series(df['montant']) if 'montant' in df.columns else pd.Series(0.0, index=df.index)
    if 'montant_paye' in df.columns:
        raw = df['montant_paye']
        s = raw.fillna('').astype(str).str.strip().str.upper()
        invalid = s.isin(_NA_VALUES) | raw.isna()
        paid = parse_float_series(raw)
        paid = paid.where(~invalid, other=pd.NA)
    else:
        paid = pd.Series([float('nan')] * len(df), index=df.index, dtype=float)

    paid_mask = _paid_mask(df)
    fill = paid.isna() & paid_mask & (declared > 0)
    paid = paid.fillna(declared.where(fill))
    paid = paid.where(paid > 0, other=pd.NA)
    return paid


def build_sector_dataframe(df, source_filename=''):
    """
    DataFrame normalisé ligne à ligne (colonnes sectorielles requises).
    Entrée : df déjà passé par read_and_clean + extract_sector_columns.
    """
    from import_utils import extract_sector_columns, _normalize_raison, _parse_etat

    sector = extract_sector_columns(df)
    if sector is None or sector.empty or 'niu' not in sector.columns:
        return pd.DataFrame()

    sector = filter_valid_niu_df(sector, 'niu')
    if sector.empty:
        return pd.DataFrame()

    out = pd.DataFrame(index=sector.index)
    out['niu'] = sector['niu']
    out['raison'] = sector['raison'].fillna('').astype(str).map(_normalize_raison) if 'raison' in sector.columns else ''
    out['montant'] = parse_float_series(sector['montant']) if 'montant' in sector.columns else 0.0
    out['montant_paye'] = resolve_montant_recu_series(sector)

    if 'etat' in sector.columns:
        out['etat_display'] = sector['etat'].fillna('').astype(str).str.strip()
        out['etat'] = sector['etat'].apply(_parse_etat)
    else:
        out['etat_display'] = ''
        out['etat'] = None

    if 'date_creation' in sector.columns:
        out['date_creation_year'], out['date_creation_month'] = parse_date_creation_series(sector['date_creation'])
    else:
        out['date_creation_year'] = pd.NA
        out['date_creation_month'] = pd.NA

    out['source_filename'] = source_filename or ''
    return out.reset_index(drop=True)


def pivot_tcd_from_dataframe(sector_df):
    """TCD par NIU — somme montants déclarés et reçus."""
    if sector_df.empty:
        return {}

    def _first_nonempty(series):
        for v in series:
            s = str(v or '').strip()
            if s:
                return s
        return ''

    def _longest_raison(series):
        vals = [str(v or '').strip() for v in series if str(v or '').strip()]
        return max(vals, key=len) if vals else ''

    def _sum_paye(series):
        valid = series.dropna()
        if valid.empty:
            return None
        return float(valid.sum())

    def _merge_etat(series):
        vals = [v for v in series if v is not None and not (isinstance(v, float) and pd.isna(v))]
        return max(int(v) for v in vals) if vals else None

    grouped = sector_df.groupby('niu', sort=True).agg(
        raison=('raison', _longest_raison),
        etat_display=('etat_display', _first_nonempty),
        etat=('etat', _merge_etat),
        montant_declare=('montant', 'sum'),
        montant_paye=('montant_paye', _sum_paye),
    )

    consolidated = {}
    for niu, row in grouped.iterrows():
        mp = row['montant_paye']
        raw_etat = row['etat']
        consolidated[niu] = {
            'raison': row['raison'] or '',
            'etat_display': row['etat_display'] or '',
            'etat': None if raw_etat is None or (isinstance(raw_etat, float) and pd.isna(raw_etat)) else int(raw_etat),
            'montant_declare': float(row['montant_declare'] or 0),
            'montant_paye': None if pd.isna(mp) else float(mp),
        }
    return consolidated


def aggregate_monthly_recu_from_dataframe(sector_df):
    """TCD mensuel : somme montants reçus par (année, mois) selon date_creation."""
    if sector_df.empty:
        return {}

    work = sector_df.copy()
    work = work[work['montant_paye'].notna() & (work['montant_paye'] > 0)]
    work = work[work['date_creation_year'].notna() & work['date_creation_month'].notna()]
    if work.empty:
        return {}

    work['date_creation_year'] = pd.to_numeric(work['date_creation_year'], errors='coerce')
    work['date_creation_month'] = pd.to_numeric(work['date_creation_month'], errors='coerce')
    work = work[work['date_creation_year'].notna() & work['date_creation_month'].notna()]
    if work.empty:
        return {}

    grouped = work.groupby(['date_creation_year', 'date_creation_month'])['montant_paye'].sum()
    by_year = {}
    for (year, month), total in grouped.items():
        y = safe_int(year)
        m = safe_int(month)
        if y is None or m is None or not (1 <= m <= 12):
            continue
        by_year.setdefault(str(y), {})[str(m)] = float(total)
    return by_year


def sector_df_to_row_dicts(sector_df):
    """Convertit le DataFrame sectoriel en dicts pour bulk_insert (sans iterrows)."""
    if sector_df.empty:
        return []

    df = sector_df.copy()
    for col in ('date_creation_year', 'date_creation_month'):
        if col in df.columns:
            df[col] = df[col].astype('Int64')

    records = df.to_dict('records')
    rows = []
    for rec in records:
        year = rec.get('date_creation_year')
        month = rec.get('date_creation_month')
        dt = None
        if pd.notna(year) and pd.notna(month):
            y, m = safe_int(year), safe_int(month)
            dt = (y, m) if y is not None and m is not None and 1 <= m <= 12 else None
        mp = rec.get('montant_paye')
        rows.append({
            'niu': rec['niu'],
            'raison': rec.get('raison') or '',
            'montant': float(rec.get('montant') or 0),
            'montant_paye': None if mp is None or (isinstance(mp, float) and pd.isna(mp)) else float(mp),
            'etat': rec.get('etat'),
            'etat_display': rec.get('etat_display') or '',
            'date_creation': dt,
            'source_filename': rec.get('source_filename') or '',
        })
    return rows
