"""Routes d'export Excel/PDF/PowerPoint."""
from flask import request, redirect, url_for, flash, send_file, session

from cdi_config import normalize_cdi
from database import SessionLocal
from extensions import login_required
from fiscal_constants import MONTANT_NEANT_MAX
from models import Contribuable
from services.stats import (
    search_contribuables, get_statut_label,
    get_defaillants_export_rows, get_neants_export_rows,
    get_relicataires_export_rows, get_declarants_export_rows,
    get_global_stats, build_export_stats_data,
)
from services.pptx_evaluation_export import build_evaluation_pptx
from services.treatment_wizard import get_treatment
from utils.export_helpers import (
    parse_export_format, fmt_export_amount, safe_export_text,
    export_table, export_stats_excel, export_stats_pdf,
)


def register(app):

    @app.route('/export')
    @login_required
    def export():
        q = request.args.get('q', '')
        cdi = request.args.get('cdi', '')
        secteur = request.args.get('secteur', '')
        etat = request.args.get('etat', '')
        statut = request.args.get('statut', '')

        db = SessionLocal()
        results, _ = search_contribuables(db, q=q, cdi=cdi, secteur=secteur, etat=etat, statut=statut, limit=10000)
        if not results:
            results = db.query(Contribuable).all()

        rows = [{
            'NIU': c.niu,
            'Raison': c.raison,
            'État': c.etat,
            'Statut': get_statut_label(c.etat),
            'CFLP': normalize_cdi(c.cdi) or c.cdi or '',
            'Secteur': c.secteur or '',
            'Montant attendu': c.montant_attendu,
            'Montant payé': c.montant_paye,
        } for c in results]
        headers = ['NIU', 'Raison', 'Statut', 'CFLP', 'Secteur', 'Montant attendu', 'Montant payé']

        excel_rows = [{
            'NIU': r['NIU'], 'Raison': r['Raison'], 'Statut': r['Statut'],
            'CFLP': r['CFLP'], 'Secteur': r['Secteur'],
            'Montant attendu': r['Montant attendu'], 'Montant payé': r['Montant payé'],
        } for r in rows]

        pdf_rows = [[
            safe_export_text(r['NIU']),
            safe_export_text(r['Raison']),
            safe_export_text(r['Statut']),
            safe_export_text(r['CFLP']),
            safe_export_text(r['Secteur']),
            fmt_export_amount(r['Montant attendu']),
            fmt_export_amount(r['Montant payé']),
        ] for r in rows]

        try:
            return export_table(
                'Export contribuables',
                excel_rows, 'export_contribuables', 'Contribuables',
                headers, pdf_rows,
            )
        finally:
            db.close()

    @app.route('/export_defaillants')
    @login_required
    def export_defaillants():
        db = SessionLocal()
        try:
            rows = get_defaillants_export_rows(db)
            excel_data = [{'NIU': r['NIU'], 'Raison sociale': r['Raison'], 'CFLP': r['CFLP']} for r in rows]
            pdf_headers = ['NIU', 'Raison sociale', 'CFLP']
            pdf_rows = [[
                safe_export_text(r['NIU']),
                safe_export_text(r['Raison']),
                safe_export_text(r['CFLP']),
            ] for r in rows]
            return export_table(
                "Liste des défaillants — n'ont pas déclaré",
                excel_data, 'liste_defaillants', 'Défaillants', pdf_headers, pdf_rows,
            )
        finally:
            db.close()

    @app.route('/export_neants')
    @login_required
    def export_neants():
        db = SessionLocal()
        try:
            rows = get_neants_export_rows(db)
            excel_data = [{
                'NIU': r['NIU'], 'Raison sociale': r['Raison'],
                'Montant déclaré': r['Montant déclaré'], 'CFLP': r['CFLP'],
            } for r in rows]
            pdf_headers = ['NIU', 'Raison sociale', 'Montant déclaré', 'CFLP']
            pdf_rows = [[
                safe_export_text(r['NIU']),
                safe_export_text(r['Raison']),
                fmt_export_amount(r['Montant déclaré']),
                safe_export_text(r['CFLP']),
            ] for r in rows]
            return export_table(
                'Liste des néants — montant déclaré 0 à 5 FCFA',
                excel_data, 'liste_neants', 'Néants', pdf_headers, pdf_rows,
            )
        finally:
            db.close()

    @app.route('/export_relicataires')
    @login_required
    def export_relicataires():
        db = SessionLocal()
        try:
            rows = get_relicataires_export_rows(db)
            excel_data = [{
                'NIU': r['NIU'], 'Raison sociale': r['Raison'],
                'Montant déclaré': r['Montant déclaré'], 'Montant payé': 'N/A',
                'CFLP': r['CFLP'],
            } for r in rows]
            pdf_headers = ['NIU', 'Raison sociale', 'Montant déclaré', 'Montant payé', 'CFLP']
            pdf_rows = [[
                safe_export_text(r['NIU']),
                safe_export_text(r['Raison']),
                fmt_export_amount(r['Montant déclaré']),
                'N/A',
                safe_export_text(r['CFLP']),
            ] for r in rows]
            return export_table(
                'Liste des relicataires — ont déclaré, rien payé (N/A)',
                excel_data, 'liste_relicataires', 'Relicataires', pdf_headers, pdf_rows,
            )
        finally:
            db.close()

    @app.route('/export_declarants')
    @login_required
    def export_declarants():
        db = SessionLocal()
        try:
            rows = get_declarants_export_rows(db)
            excel_data = [{
                'NIU': r['NIU'], 'Raison sociale': r['Raison'],
                'Montant déclaré': r['Montant déclaré'], 'Montant payé': r['Montant payé'],
                'Catégorie': r['Statut'], 'CFLP': r['CFLP'],
            } for r in rows]
            pdf_headers = ['NIU', 'Raison sociale', 'Montant déclaré', 'Montant payé', 'Catégorie', 'CFLP']
            pdf_rows = [[
                safe_export_text(r['NIU']),
                safe_export_text(r['Raison']),
                fmt_export_amount(r['Montant déclaré']),
                fmt_export_amount(r['Montant payé']),
                safe_export_text(r['Statut']),
                safe_export_text(r['CFLP']),
            ] for r in rows]
            stats = get_global_stats(db)
            return export_table(
                f'Liste des déclarants — dont {stats["pct_neants_in_declarants"]}% néants (0 à {int(MONTANT_NEANT_MAX)} FCFA)',
                excel_data, 'liste_declarants', 'Déclarants', pdf_headers, pdf_rows,
            )
        finally:
            db.close()

    @app.route('/export_stats')
    @login_required
    def export_stats():
        db = SessionLocal()
        try:
            data = build_export_stats_data(db)
            if parse_export_format() == 'pdf':
                return export_stats_pdf(data)
            return export_stats_excel(data)
        finally:
            db.close()

    @app.route('/export_evaluation_pptx')
    @login_required
    def export_evaluation_pptx():
        """Rapport PowerPoint — modèle Evaluation performance CRICEXT."""
        db = SessionLocal()
        try:
            treatment = get_treatment(db, session.get('treatment_id'))
            period = None
            if treatment:
                period = f"{treatment.name} — {treatment.period}" if treatment.period else treatment.name
            bio, filename = build_evaluation_pptx(db, period_label=period)
            return send_file(
                bio,
                download_name=filename,
                as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation',
            )
        except FileNotFoundError as e:
            flash(str(e))
            return redirect(url_for('dashboard'))
        except ModuleNotFoundError as e:
            flash(str(e))
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f'Erreur export PowerPoint : {e}')
            return redirect(url_for('dashboard'))
        finally:
            db.close()

    @app.route('/export_pdf')
    @login_required
    def export_pdf():
        return redirect(url_for('export_stats', format='pdf'))
