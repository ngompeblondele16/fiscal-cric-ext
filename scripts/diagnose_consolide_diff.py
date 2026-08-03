"""Compare manual consolidated file vs app pipeline on same source files."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from niu import is_valid_niu, normalize_niu
from import_utils import process_sector_files_phase1, read_and_clean, extract_sector_columns, pivot_tcd_from_rows
from services.excel_pipeline import build_sector_dataframe, pivot_tcd_from_dataframe

TRAIN = r"d:\Documents DGI\Dossier d'entrainement"
MANUAL = os.path.join(TRAIN, "Fichier consolide.xlsx")

SOURCE_FILES = [
    "DECLATVAA Janv Juin 2025.xlsx",
    "DECLATVAA Janv Juin 2026.xlsx",
    "DECLATVAA JUIN.xlsx",
    "Marche juin.xlsx",
    "Mine juin.xlsx",
    "Mutation juin.xlsx",
]

def load_manual():
    df = pd.read_excel(MANUAL)
    niu_col = "niu"
    amt_col = [c for c in df.columns if "montant" in str(c).lower() or "somme" in str(c).lower()][0]
    df = df.copy()
    df["_niu_raw"] = df[niu_col].astype(str).str.strip()
    df["_niu_norm"] = df["_niu_raw"].map(normalize_niu)
    df["_amt"] = pd.to_numeric(df[amt_col], errors="coerce").fillna(0)
    return df, amt_col

def run_app_consolidation():
    paths = [os.path.join(TRAIN, f) for f in SOURCE_FILES if os.path.isfile(os.path.join(TRAIN, f))]
    result = process_sector_files_phase1(paths)
    consolidated = result.get("consolidated") or {}
    return consolidated, result

def main():
    manual_df, amt_col = load_manual()
    print("=== MANUEL ===")
    print("rows", len(manual_df), "col montant:", amt_col)
    print("sum montant", manual_df["_amt"].sum())
    total_rows = manual_df["_niu_raw"].str.upper().str.startswith("TOTAL")
    print("lignes Total* (artefact TCD Excel):", total_rows.sum())
    valid = manual_df["_niu_norm"].map(is_valid_niu)
    print("NIU valides (format P/M):", valid.sum(), "invalides:", (~valid).sum())
    print("exemples invalides:", manual_df.loc[~valid, "_niu_raw"].head(10).tolist())

    # Dedupe manual like real NIU only
    manual_valid = manual_df[valid].copy()
    print("NIU uniques (valides seulement):", manual_valid["_niu_norm"].nunique())
    print("sum montant (valides):", manual_valid["_amt"].sum())

    print("\n=== APP (process_sector_files_phase1) ===")
    try:
        consolidated, result = run_app_consolidation()
    except Exception as e:
        print("ERREUR pipeline:", e)
        import traceback
        traceback.print_exc()
        return

    print("controls:", {k: result.get(k) for k in ("raw_lines", "valid_lines", "contribuable_count", "files_processed") if k in result})
    print("NIU consolidés:", len(consolidated))
    app_sum = sum(v.get("montant_declare", 0) or 0 for v in consolidated.values())
    print("sum montant_declare:", app_sum)

    # Compare sets
    manual_nius = set(manual_valid["_niu_norm"])
    app_nius = set(consolidated.keys())
    only_manual = manual_nius - app_nius
    only_app = app_nius - manual_nius
    common = manual_nius & app_nius
    print("\n=== ECARTS NIU ===")
    print("communs:", len(common), "seulement manuel:", len(only_manual), "seulement app:", len(only_app))
    if only_manual:
        print("exemples only_manual:", list(only_manual)[:15])
    if only_app:
        print("exemples only_app:", list(only_app)[:15])

    # Amount diffs on common
    diffs = []
    for niu in common:
        m_amt = float(manual_valid.loc[manual_valid["_niu_norm"] == niu, "_amt"].sum())
        a_amt = float(consolidated[niu].get("montant_declare", 0) or 0)
        if abs(m_amt - a_amt) > 0.01:
            diffs.append((niu, m_amt, a_amt, m_amt - a_amt))
    diffs.sort(key=lambda x: abs(x[3]), reverse=True)
    print("\nNIU avec montants différents:", len(diffs))
    for row in diffs[:20]:
        print(f"  {row[0]}: manuel={row[1]:,.0f} app={row[2]:,.0f} delta={row[3]:,.0f}")

    # Per-file stats
    print("\n=== PAR FICHIER SOURCE (app) ===")
    per_file = result.get("per_file") or result.get("files") or []
    if isinstance(per_file, dict):
        for fn, info in per_file.items():
            print(fn, info)
    elif isinstance(per_file, list):
        for info in per_file:
            print(info)

if __name__ == "__main__":
    main()
