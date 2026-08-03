import os
import pandas as pd

manual = r"d:\Documents DGI\Dossier d'entrainement\Fichier consolide.xlsx"
app = r"D:\Documents DGI\Fiscal\fiscal\uploads\fichier_consolide.xlsx"

for label, path in [("MANUEL", manual), ("APP", app)]:
    print("===", label, "exists=", os.path.isfile(path), "===")
    if not os.path.isfile(path):
        continue
    df = pd.read_excel(path)
    print("shape", df.shape)
    print("cols", list(df.columns))
    niu_col = next((c for c in df.columns if str(c).lower().strip() in ("niu", "n_i_u")), df.columns[0])
    mcols = [c for c in df.columns if any(k in str(c).lower() for k in ("montant", "payer", "total"))]
    print("niu col", niu_col, "montant cols", mcols)
    if mcols:
        s = pd.to_numeric(df[mcols[0]].astype(str).str.replace(" ", "").str.replace(",", "."), errors="coerce")
        print("sum", mcols[0], s.sum())
    print("unique niu", df[niu_col].nunique())
    print(df.head(3).to_string())
    print()
