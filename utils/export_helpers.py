"""Helpers partagés pour les exports Excel/PDF."""
from io import BytesIO

import pandas as pd
from flask import Response, flash, redirect, request, send_file, url_for

from pdf_utils import generate_stats_pdf, generate_table_pdf


def parse_export_format():
    fmt = (request.args.get('format') or 'excel').lower().strip()
    if fmt in ('pdf',):
        return 'pdf'
    return 'excel'


def fmt_export_amount(val):
    """Format montant pour export PDF/Excel (sans exception)."""
    if val is None or val == 'N/A':
        return 'N/A'
    if isinstance(val, float) and val != val:
        return ''
    try:
        return f"{int(round(float(val))):,}".replace(',', ' ')
    except (TypeError, ValueError):
        s = str(val).strip()
        return s if s and s.lower() not in ('nan', 'none', 'null') else ''


def safe_export_text(val, default=''):
    """Texte sûr pour les lignes PDF (None, NaN, nombres)."""
    if val is None:
        return default
    if isinstance(val, float) and val != val:
        return default
    s = str(val).strip()
    if not s or s.lower() in ('nan', 'none', 'null'):
        return default
    return s


def send_pdf(bio, filename):
    bio.seek(0)
    return send_file(
        bio,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename,
        max_age=0,
        etag=False,
    )


def pdf_export_error(exc, fallback_route='dashboard'):
    msg = f"Erreur lors de la génération du PDF : {exc}"
    if parse_export_format() == 'pdf':
        return Response(msg, status=500, mimetype='text/plain; charset=utf-8')
    flash(msg)
    return redirect(request.referrer or url_for(fallback_route))


def export_liste_excel(df_rows, sheet_name, filename):
    bio = BytesIO()
    pd.DataFrame(df_rows).to_excel(bio, index=False, sheet_name=sheet_name)
    bio.seek(0)
    return send_file(bio, download_name=filename, as_attachment=True)


def export_table(title, excel_rows, filename_base, sheet_name, pdf_headers, pdf_rows, header_color=None):
    """Exporte une liste au format Excel ou PDF selon ?format=excel|pdf."""
    if parse_export_format() == 'pdf':
        try:
            bio = generate_table_pdf(
                title,
                f"{len(pdf_rows)} enregistrement(s)",
                pdf_headers,
                pdf_rows,
                header_color=header_color,
            )
            return send_pdf(bio, f'{filename_base}.pdf')
        except Exception as exc:
            return pdf_export_error(exc)
    return export_liste_excel(excel_rows, sheet_name, f'{filename_base}.xlsx')


def pdf_row_amount(row, *keys, default=0):
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return default


def build_stats_pdf_payload(data):
    stats = data['stats']
    return {
        'global': data.get('global') or [
            {'metrique': 'Total contribuables', 'valeur': stats['total']},
            {'metrique': 'Défaillants', 'valeur': stats['defaillants']},
            {'metrique': 'Relicataires', 'valeur': stats['relicataires']},
            {'metrique': 'Déclarants', 'valeur': stats.get('declarants_total', stats['declarants'])},
            {'metrique': 'Montant attendu — déclaré (FCFA)', 'valeur': stats['sum_declare_attendu']},
            {'metrique': 'Montant reçu — payé (FCFA)', 'valeur': stats['sum_paye']},
            {'metrique': 'Taux d\'encaissement (%)', 'valeur': round(stats['sum_paye'] / stats['sum_declare_attendu'] * 100, 1) if stats.get('sum_declare_attendu') else 0},
        ],
        'cflp': [{
            'cflp': r.get('CFLP') or r.get('cdi') or 'N/A',
            'count': r.get('Déclarants') or r.get('count') or 0,
            'sum_declared': pdf_row_amount(r, 'Montant', 'montant', 'Montant déclaré'),
        } for r in data.get('cdi', [])],
        'secteur': [{
            'secteur': r.get('Secteur') or r.get('secteur') or 'N/A',
            'count': r.get('Nombre') or r.get('count') or 0,
            'sum_declared': pdf_row_amount(r, 'Montant déclaré', 'Montant', 'montant'),
        } for r in data.get('secteur', [])],
        'sous_secteur': [],
        'defaillants': data.get('defaillants', []),
        'relicataires': data.get('relicataires', []),
        'declarants': data.get('declarants', []),
        'neants': stats.get('neants', 0),
        'etat': data.get('etat', []),
        'taux_secteur': data.get('taux_secteur', []),
        'taux_structure': data.get('taux_structure', []),
        'performance_cflp': data.get('performance_cflp', []),
        'montants_secteur': data.get('montants_secteur', []),
    }


def export_stats_excel(data):
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine='openpyxl') as writer:
        pd.DataFrame(data['global']).to_excel(writer, sheet_name='Statistiques_Globales', index=False)
        pd.DataFrame(data['cdi']).to_excel(writer, sheet_name='Par_CFLP', index=False)
        pd.DataFrame(data['secteur']).to_excel(writer, sheet_name='Par_Secteur', index=False)
        pd.DataFrame(data['etat']).to_excel(writer, sheet_name='Par_Etat', index=False)
        if data.get('taux_secteur'):
            pd.DataFrame(data['taux_secteur']).to_excel(writer, sheet_name='Taux_Secteur', index=False)
        if data.get('taux_structure'):
            pd.DataFrame(data['taux_structure']).to_excel(writer, sheet_name='Taux_CFLP', index=False)
        if data.get('performance_cflp'):
            pd.DataFrame(data['performance_cflp']).to_excel(writer, sheet_name='Performance_CFLP', index=False)
        if data.get('montants_secteur'):
            pd.DataFrame(data['montants_secteur']).to_excel(writer, sheet_name='Montants_Secteur', index=False)
        pd.DataFrame(data['defaillants']).to_excel(writer, sheet_name='Defaillants', index=False)
        pd.DataFrame(data['relicataires']).to_excel(writer, sheet_name='Relicataires', index=False)
        pd.DataFrame(data['declarants']).to_excel(writer, sheet_name='Declarants', index=False)
    bio.seek(0)
    return send_file(bio, download_name='statistiques_fiscales.xlsx', as_attachment=True)


def export_stats_pdf(data):
    try:
        pdf_bio = generate_stats_pdf(build_stats_pdf_payload(data))
        return send_pdf(pdf_bio, 'rapport_statistiques.pdf')
    except Exception as exc:
        return pdf_export_error(exc, 'statistiques')
