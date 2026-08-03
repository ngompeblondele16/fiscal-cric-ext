"""Routes listes fiscales : défaillants, néants, relicataires, déclarants."""
from flask import render_template, redirect, url_for

from database import SessionLocal
from extensions import login_required
from fiscal_constants import MONTANT_NEANT_MAX
from services.stats import (
    get_global_stats,
    get_defaillants_export_rows,
    get_neants_export_rows,
    get_relicataires_export_rows,
    get_declarants_export_rows,
)


def register(app):

    @app.route('/defaillants')
    @login_required
    def defaillants_list():
        db = SessionLocal()
        try:
            rows = get_defaillants_export_rows(db)
            return render_template('liste_fiscale.html',
                title='Défaillants',
                description='Absents du consolidé (#N/A RECHERCHEV) — données du dernier import — ',
                rows=rows, total=len(rows), show_montant=False,
                export_endpoint='export_defaillants')
        finally:
            db.close()

    @app.route('/neants')
    @login_required
    def neants_list():
        return redirect(url_for('declarants_list'))

    @app.route('/relicataires')
    @login_required
    def relicataires_list():
        db = SessionLocal()
        try:
            rows = get_relicataires_export_rows(db)
            return render_template('liste_fiscale.html',
                title='Relicataires',
                description='Ont déclaré (montant &gt; 10 FCFA) mais rien payé — état 2 — ',
                rows=rows, total=len(rows),
                show_montant_declare=True, show_montant_paye=True,
                export_endpoint='export_relicataires')
        finally:
            db.close()

    @app.route('/declarants')
    @login_required
    def declarants_list():
        db = SessionLocal()
        try:
            rows = get_declarants_export_rows(db)
            stats = get_global_stats(db)
            return render_template('liste_fiscale.html',
                title='Déclarants',
                description=f'Montant déclaré &gt; {int(MONTANT_NEANT_MAX)} FCFA et payé — état 3 — {stats["declarants"]} ligne(s) — ',
                rows=rows, total=len(rows),
                show_montant_declare=True, show_montant_paye=True, show_categorie=True,
                export_endpoint='export_declarants')
        finally:
            db.close()
