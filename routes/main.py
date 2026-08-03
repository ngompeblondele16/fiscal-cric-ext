"""Routes principales : tableau de bord, recherche, rapports."""
from datetime import datetime

from flask import render_template, request, redirect, url_for, flash

from database import SessionLocal
from extensions import login_required
from fiscal_constants import MONTANT_NEANT_MAX
from models import Contribuable, ImportHistory
from services.stats import (
    get_global_stats, get_by_cdi, get_by_secteur,
    get_cdi_chart_data, get_secteur_chart_data, get_recettes_mensuelles_data,
    get_cflp_declaration_rates, get_treatment_comparison, get_treatment_history,
    get_taux_declaration_by_secteur, get_taux_declaration_by_sous_secteur, get_taux_declaration_by_structure,
    get_performance_by_cflp, get_montants_by_secteur, get_reliquataires_by_sous_secteur,
    search_contribuables, get_filter_options, get_defaillants, get_relicataires,
    get_declarants, get_statut_label, get_evolution_data,
)
from services.ca_analysis import get_ca_top10_dashboard


def register(app):

    @app.route('/')
    @login_required
    def dashboard():
        db = SessionLocal()
        stats = get_global_stats(db)
        imports = db.query(ImportHistory).order_by(ImportHistory.date_import.desc()).limit(6).all()
        cdi_chart = get_cdi_chart_data(db)
        cflp_rates = get_cflp_declaration_rates(db)
        secteur_chart = get_secteur_chart_data(db)
        recettes_mensuelles = get_recettes_mensuelles_data(db)
        ca_top10 = get_ca_top10_dashboard(db)
        comparison = get_treatment_comparison(db)
        treatment_history = get_treatment_history(db, limit=5)
        taux_global = stats['taux_declaration']

        return render_template(
            'dashboard.html',
            total=stats['total'],
            declared=stats['declarants'],
            paid=stats['paid'],
            defaillants=stats['defaillants'],
            neants=stats['neants'],
            relicataires=stats['relicataires'],
            declarants=stats['declarants'],
            declarants_total=stats['declarants_total'],
            pct_neants_in_declarants=stats['pct_neants_in_declarants'],
            non_declared=stats['non_declared'],
            sum_declared=stats['sum_montant'],
            imports=imports,
            cdi_chart=cdi_chart,
            cflp_rates=cflp_rates,
            secteur_chart=secteur_chart,
            recettes_mensuelles=recettes_mensuelles,
            ca_top10=ca_top10,
            comparison=comparison,
            treatment_history=treatment_history,
            taux_global=taux_global,
            taux_defaillant=stats['taux_defaillant'],
            taux_neant=stats['taux_neant'],
            taux_relicataire=stats['taux_relicataire'],
            taux_declarant=stats['taux_declarant'],
            stats=stats,
            montant_neant_max=MONTANT_NEANT_MAX,
        )

    @app.route('/search')
    @login_required
    def search():
        q = request.args.get('q', '').strip()
        cdi = request.args.get('cdi', '')
        secteur = request.args.get('secteur', '')
        etat = request.args.get('etat', '')
        statut = request.args.get('statut', '')

        db = SessionLocal()
        stats = get_global_stats(db)
        total_count = stats['total']
        pct_declarants = round(stats['taux_declaration']) if total_count else 0
        pct_neants_in_decl = stats['pct_neants_in_declarants']
        pct_relicataires = 0
        pct_non_decl = round(stats['taux_defaillant']) if total_count else 0
        pct_neant = round(stats['taux_neant']) if total_count else 0

        filters = get_filter_options(db)
        results, filtered_count = search_contribuables(
            db, q=q, cdi=cdi, secteur=secteur, etat=etat, statut=statut
        )

        return render_template(
            'search.html',
            results=results,
            q=q,
            cdi=cdi,
            secteur=secteur,
            etat=etat,
            statut=statut,
            total_count=total_count,
            filtered_count=filtered_count,
            pct_declarants=pct_declarants,
            pct_neants_in_decl=pct_neants_in_decl,
            declarants_total=stats['declarants_total'],
            pct_relicataires=pct_relicataires,
            pct_non_decl=pct_non_decl,
            cdi_list=filters['cflp_list'],
            cflp_centres=filters['cflp_centres'],
            cflp_extra=filters['cflp_extra'],
            secteur_list=filters['secteur_list'],
            montant_neant_max=MONTANT_NEANT_MAX,
        )

    @app.route('/statistiques')
    @login_required
    def statistiques():
        return redirect(url_for('dashboard'))

    @app.route('/reports')
    @login_required
    def reports():
        db = SessionLocal()
        try:
            stats = get_global_stats(db)
            by_cdi = get_by_cdi(db)
            by_secteur = get_by_secteur(db)
            evolution = get_evolution_data(db)
            cdi_stats = [{'cdi': r['cdi'], 'count': r['declares'], 'sum_declared': r['montant']} for r in by_cdi[:5]]
            secteur_stats = by_secteur[:6]
            max_sect_montant = max((r['montant'] for r in secteur_stats), default=1) or 1
            secteur_chart = [
                {'name': (r['secteur'][:12] + '…') if len(r['secteur'] or '') > 12 else (r['secteur'] or 'N/A'),
                 'count': r['count'],
                 'height': max(12, int(r['montant'] / max_sect_montant * 100))}
                for r in secteur_stats
            ]
            evolution_values = evolution.get('values') or []
            max_evo = max(evolution_values) if evolution_values else 1
            evolution_chart = [
                {'height': max(8, int(v / max_evo * 100)) if max_evo else 8}
                for v in evolution_values[-10:]
            ]
            non_decl_list = get_defaillants(db, limit=8)
            relicataires_list = get_relicataires(db, limit=8)
            declarants_list = get_declarants(db, limit=8)

            non_decl_data = [{
                'niu': c.niu, 'raison': c.raison or '-',
                'montant_attendu': c.montant_attendu, 'cdi': c.cdi or '',
            } for c in non_decl_list]

            relicataires_data = [{
                'niu': c.niu, 'raison': c.raison or '-',
                'montant_declare': c.montant_declare if c.montant_declare is not None else 0,
                'montant_paye': 'N/A', 'cdi': c.cdi or '',
            } for c in relicataires_list]

            declarants_data = [{
                'niu': c.niu, 'raison': c.raison or '-',
                'montant_declare': c.montant_declare if c.montant_declare is not None else 0,
                'montant_paye': c.montant_paye if c.montant_paye is not None else 'N/A',
                'categorie': get_statut_label(c.etat),
                'cdi': c.cdi or '',
            } for c in declarants_list]

            conformity_pct = stats['taux_declaration']
            pct_paid = round(stats['paid'] / stats['total'] * 100) if stats['total'] else 0
            sum_declare_attendu = stats['sum_declare_attendu']
            sum_recu = stats['sum_paye']
            taux_encaissement = round(sum_recu / sum_declare_attendu * 100, 1) if sum_declare_attendu else 0.0
            taux_secteur = get_taux_declaration_by_secteur(db)
            taux_sous_secteur = get_taux_declaration_by_sous_secteur(db)
            taux_structure = get_taux_declaration_by_structure(db)
            performance_cflp = get_performance_by_cflp(db)
            montants_secteur = get_montants_by_secteur(db)
            reliquataires_sous_secteur = get_reliquataires_by_sous_secteur(db)
            report_date = datetime.now().strftime('%d/%m/%Y')

            return render_template(
                'reports.html',
                total=stats['total'],
                declared=stats['declared'],
                paid=stats['paid'],
                non_declared=stats['non_declared'],
                defaillants=stats['defaillants'],
                relicataires=stats['relicataires'],
                neants=stats['neants'],
                declarants_total=stats['declarants_total'],
                pct_neants_in_declarants=stats['pct_neants_in_declarants'],
                declarants=stats['declarants'],
                sum_declared=sum_declare_attendu,
                sum_declare_attendu=sum_declare_attendu,
                sum_recu=sum_recu,
                taux_encaissement=taux_encaissement,
                sum_paye=stats['sum_paye'],
                taux_secteur=taux_secteur,
                taux_sous_secteur=taux_sous_secteur,
                taux_structure=taux_structure,
                performance_cflp=performance_cflp,
                montants_secteur=montants_secteur,
                reliquataires_sous_secteur=reliquataires_sous_secteur,
                cdi_stats=cdi_stats,
                secteur_chart=secteur_chart,
                evolution_chart=evolution_chart,
                non_decl_data=non_decl_data,
                relicataires_data=relicataires_data,
                declarants_data=declarants_data,
                conformity_pct=conformity_pct,
                pct_paid=pct_paid,
                report_date=report_date,
                montant_neant_max=MONTANT_NEANT_MAX,
            )
        finally:
            db.close()

    @app.route('/traitement')
    @login_required
    def traitement():
        return redirect(url_for('upload'))

    @app.route('/compare')
    @login_required
    def compare():
        return redirect(url_for('upload'))

    @app.route('/process_queue', methods=['POST'])
    @login_required
    def process_queue():
        flash('Utilisez Import — Étape 1 puis Étape 2.')
        return redirect(url_for('upload'))

    @app.route('/pending_imports')
    @login_required
    def pending_imports():
        return redirect(url_for('upload'))
