"""Routes d'import : wizard de traitement fiscal complet."""
import json
import os
import uuid
from datetime import datetime
from io import BytesIO

import pandas as pd
from flask import render_template, request, redirect, url_for, session, flash, send_file
from werkzeug.utils import secure_filename

from config import UPLOAD_DIR
from database import SessionLocal
from extensions import login_required
from import_utils import (
    count_file_data_rows, run_phase2_vlookup, run_phase3_sector_lookup,
    consolidated_is_ready, get_consolidated_preview, clear_consolidated_artifacts,
    load_consolidated_dict, load_consolidated_meta, safe_remove_file,
    _consolidated_rows_for_export_sans_etat,
)
from models import PendingImport, Contribuable
from services.file_analysis import analyze_upload_file
from services.import_workflow import run_phase1_and_notify
from services.sector_export import (
    sector_tcd_to_bytes, sous_secteur_tcd_to_bytes, ca_sous_secteur_to_bytes,
    reliquataires_sous_secteur_to_bytes,
)
from services.vlookup_export import vlookup_comparison_to_bytes, export_download_name
from services.en_ligne_store import sectors_applied
from services.stats import get_global_stats, save_treatment_snapshot
from services.ca_analysis import (
    run_ca_analysis, ca_table_rows, ca_analysis_ready, clear_ca_analysis, _parse_year,
    consolide_ca_export_rows, inspect_ca_upload_fast, ca_negative_gap_details,
)
from services.treatment_wizard import (
    WIZARD_STEPS, create_treatment, get_treatment, log_step, set_step,
    finish_treatment, load_log, sector_kpi_rows_for_export, sous_secteur_kpi_rows_for_export,
    reliquataires_sous_secteur_rows_for_export,
)


def _pending_ca_slot(pending):
    try:
        data = json.loads(pending.analysis_json or '{}')
        return data.get('ca_slot', 'current')
    except (json.JSONDecodeError, TypeError, AttributeError):
        return 'current'


def _wizard_context(db):
    treatment = get_treatment(db, session.get('treatment_id'))
    if session.get('treatment_id') and not treatment:
        session.pop('treatment_id', None)
    wizard_step = treatment.current_step if treatment else 1

    pendings = db.query(PendingImport).order_by(PendingImport.date_added.desc()).all()
    updated_counts = False
    for p in pendings:
        # Les fichiers CA sont volumineux : éviter un recomptage coûteux
        # à chaque affichage du wizard si le nombre de lignes est déjà stocké.
        if (p.nb_rows or 0) <= 0 and p.filepath and os.path.isfile(p.filepath):
            if (p.import_phase or 1) == 4:
                # Recompte ciblé seulement si 0 ligne affichée (corrige certains cas Excel CA).
                analysis = inspect_ca_upload_fast(p.filepath)
                p.nb_rows = int(analysis.get('nb_rows') or 0)
            else:
                p.nb_rows = count_file_data_rows(p.filepath)
            updated_counts = True
    if updated_counts:
        db.commit()

    pendings_phase1 = [p for p in pendings if (p.import_phase or 1) == 1]
    pendings_phase2 = [p for p in pendings if (p.import_phase or 1) == 2]
    pendings_phase3 = [p for p in pendings if (p.import_phase or 1) == 3]
    pendings_phase4 = [p for p in pendings if (p.import_phase or 1) == 4]
    pendings_ca_current = [p for p in pendings_phase4 if _pending_ca_slot(p) != 'previous']
    pendings_ca_previous = [p for p in pendings_phase4 if _pending_ca_slot(p) == 'previous']

    consolidated_ready = consolidated_is_ready(db)
    consolidated_count = 0
    consolidation_meta = None
    preview_rows = []
    if consolidated_ready:
        preview_rows, consolidated_count = get_consolidated_preview(100, db_session=db)
        consolidation_meta = load_consolidated_meta(db)

    phase2_complete = db.query(Contribuable).filter(Contribuable.etat.isnot(None)).count() > 0
    sectors_complete = sectors_applied(db) if phase2_complete else False

    sector_kpi = []
    sous_secteur_kpi = []
    reliquataires_sous_secteur = []
    global_stats = None
    if phase2_complete:
        global_stats = get_global_stats(db)
        sector_kpi = sector_kpi_rows_for_export(db)
        if sectors_complete:
            sous_secteur_kpi = sous_secteur_kpi_rows_for_export(db)
            reliquataires_sous_secteur = reliquataires_sous_secteur_rows_for_export(db)

    ca_rows = []
    ca_info = None
    ca_complete = ca_analysis_ready(db)
    if ca_complete:
        ca_rows, ca_info = ca_table_rows(db)

    treatment_period_year = _parse_year(treatment.period if treatment else None)

    return {
        'wizard_steps': WIZARD_STEPS,
        'wizard_step': wizard_step,
        'treatment': treatment,
        'treatment_log': load_log(treatment),
        'pendings_phase1': pendings_phase1,
        'pendings_phase2': pendings_phase2,
        'pendings_phase3': pendings_phase3,
        'pendings_phase4': pendings_phase4,
        'pendings_ca_current': pendings_ca_current,
        'pendings_ca_previous': pendings_ca_previous,
        'consolidated_ready': consolidated_ready,
        'consolidated_count': consolidated_count,
        'consolidation_meta': consolidation_meta,
        'preview_rows': preview_rows,
        'phase2_complete': phase2_complete,
        'sectors_complete': sectors_complete,
        'sector_kpi': sector_kpi,
        'sous_secteur_kpi': sous_secteur_kpi,
        'reliquataires_sous_secteur': reliquataires_sous_secteur,
        'global_stats': global_stats,
        'ca_complete': ca_complete,
        'ca_rows': ca_rows,
        'ca_info': ca_info,
        'treatment_period_year': treatment_period_year,
    }


def register(app):

    @app.route('/upload', methods=['GET', 'POST'])
    @login_required
    def upload():
        if request.method == 'POST':
            files = request.files.getlist('files') or request.files.getlist('file')
            files = [f for f in files if f and f.filename]

            if not files:
                flash('Aucun fichier sélectionné.')
                return redirect(url_for('upload'))

            try:
                import_phase = int(request.form.get('phase', '1'))
            except (TypeError, ValueError):
                import_phase = 1

            if import_phase == 1 and not session.get('treatment_id'):
                flash('Créez d\'abord un nouveau traitement (étape 1).')
                return redirect(url_for('upload'))

            db = SessionLocal()
            treatment = get_treatment(db, session.get('treatment_id'))
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            added = 0
            rows_added = 0

            try:
                if import_phase == 2:
                    if not consolidated_is_ready(db):
                        flash('Consolidation requise avant le fichier en ligne.')
                        set_step(db, treatment, 2, commit=False)
                        db.commit()
                        return redirect(url_for('upload'))
                elif import_phase == 3 and not db.query(Contribuable).filter(Contribuable.etat.isnot(None)).count():
                    flash('Comparaison RECHERCHEV requise avant la table secteurs.')
                    return redirect(url_for('upload'))
                elif import_phase == 4 and not consolidated_is_ready(db):
                    flash('Consolidation requise avant l\'import CA.')
                    return redirect(url_for('upload'))

                ca_slot = request.form.get('ca_slot', 'current') if import_phase == 4 else None

                for f in files:
                    safe_name = secure_filename(f.filename) or 'import.xlsx'
                    unique_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}_{safe_name}"
                    path = os.path.join(UPLOAD_DIR, unique_name)
                    f.save(path)

                    try:
                        # Les fichiers CA peuvent être très volumineux : validation rapide dédiée
                        # (aperçu en-têtes + comptage), pour éviter une lecture intégrale à l'upload.
                        if import_phase == 4:
                            analysis = inspect_ca_upload_fast(path)
                        else:
                            analysis = analyze_upload_file(path, expected_phase=import_phase)
                        ftype = analysis['file_type']
                        nb_rows = analysis['nb_rows']

                        if not analysis['ok']:
                            for err in analysis['errors']:
                                flash(f"{f.filename} : {err}")
                            if analysis['errors']:
                                safe_remove_file(path)
                                continue

                        pending = PendingImport(
                            filename=f.filename,
                            filepath=path,
                            user=session.get('user'),
                            file_type=ftype,
                            import_phase=import_phase,
                            nb_rows=nb_rows,
                            status='importe' if analysis['ok'] else 'erreur',
                            analysis_json=json.dumps({'ca_slot': ca_slot}) if ca_slot else '',
                        )
                        db.add(pending)
                        added += 1
                        rows_added += nb_rows

                        if treatment:
                            detail = f"{f.filename} · {nb_rows:,} ligne(s)".replace(',', ' ')
                            log_step(db, treatment, f'phase{import_phase}', 'Fichier importé', detail)
                    except Exception as e:
                        safe_remove_file(path)
                        flash(f"Erreur pour {f.filename} : {e}")

                if added:
                    db.commit()
                    if treatment:
                        if import_phase == 4:
                            set_step(db, treatment, 6, commit=False)
                        else:
                            set_step(db, treatment, max(treatment.current_step, import_phase + 1), commit=False)
                        db.commit()
                    labels = {1: 'déclaratif(s)', 2: 'en ligne', 3: 'secteur(s)', 4: 'CA'}
                    flash(
                        f"{added} fichier(s) {labels.get(import_phase, '')} importé(s) "
                        f"({rows_added:,} ligne(s)) — lancez le traitement.".replace(',', ' ')
                    )
                else:
                    db.rollback()
            except Exception as e:
                db.rollback()
                err_msg = str(e)
                if 'WinError 32' in err_msg or 'utilisé par un autre processus' in err_msg:
                    flash('Fichier verrouillé : fermez Excel puis réessayez.')
                flash(f"Erreur import : {err_msg}")
            finally:
                db.close()

            return redirect(url_for('upload'))

        db = SessionLocal()
        try:
            ctx = _wizard_context(db)
            return render_template('upload.html', **ctx)
        finally:
            db.close()

    @app.route('/import/create', methods=['POST'])
    @login_required
    def import_create_treatment():
        name = request.form.get('name', '').strip()
        period = request.form.get('period', '').strip()
        db = SessionLocal()
        try:
            clear_consolidated_artifacts(db)
            clear_ca_analysis(db)
            for p in db.query(PendingImport).all():
                if p.filepath:
                    safe_remove_file(p.filepath)
                db.delete(p)
            db.query(Contribuable).delete()
            db.commit()

            treatment = create_treatment(db, name, period, user=session.get('user', 'admin'))
            session['treatment_id'] = treatment.id
            session.pop('import_step', None)
            flash(f'Traitement « {treatment.name} » créé — période {treatment.period}.')
        finally:
            db.close()
        return redirect(url_for('upload'))

    @app.route('/delete_pending/<int:pending_id>')
    @login_required
    def delete_pending(pending_id):
        db = SessionLocal()
        pending = db.query(PendingImport).filter_by(id=pending_id).first()
        if pending:
            filepath = pending.filepath
            db.delete(pending)
            db.commit()
            if filepath:
                safe_remove_file(filepath)
            flash(f"Fichier {pending.filename} retiré de la file.")
        db.close()
        return redirect(url_for('upload'))

    @app.route('/process_phase1', methods=['POST'])
    @login_required
    def process_phase1():
        db = SessionLocal()
        treatment = get_treatment(db, session.get('treatment_id'))
        try:
            result = run_phase1_and_notify(db, session.get('user', 'admin'))
            if result is None:
                flash('Aucun fichier déclaratif en attente.')
                return redirect(url_for('upload'))

            if not result.get('success'):
                flash(result.get('error') or 'Échec consolidation.')
                for err in (result.get('errors') or [])[:5]:
                    flash(err)
                if treatment:
                    log_step(db, treatment, 'consolidated', 'Échec consolidation', result.get('error', ''), 'error', commit=True)
                return redirect(url_for('upload'))

            controls = result.get('controls') or {}
            if treatment:
                log_step(
                    db, treatment, 'consolidated', 'Consolidation terminée',
                    f"{controls.get('nb_fichiers', 0)} fichier(s) · "
                    f"{result['nb_contribuables']} contribuable(s) · "
                    f"{controls.get('nb_lignes', 0):,} ligne(s) valide(s) · "
                    f"phase 2 réinitialisée".replace(',', ' '),
                )
                set_step(db, treatment, 3)
            flash(result.get('notification') or f"Consolidation — {result['nb_contribuables']} contribuable(s).")
        except Exception as e:
            db.rollback()
            flash(f'Erreur Phase 1 : {e}')
        finally:
            db.close()
        return redirect(url_for('upload'))

    @app.route('/process_phase2', methods=['POST'])
    @login_required
    def process_phase2():
        db = SessionLocal()
        treatment = get_treatment(db, session.get('treatment_id'))
        try:
            if not consolidated_is_ready(db):
                flash('Phase 1 requise.')
                return redirect(url_for('upload'))
            pendings = db.query(PendingImport).filter(PendingImport.import_phase == 2).all()
            if not pendings:
                flash('Aucun fichier en ligne en attente.')
                return redirect(url_for('upload'))

            filepaths = [p.filepath for p in pendings if p.filepath and os.path.exists(p.filepath)]
            result = run_phase2_vlookup(db, filepaths, user=session.get('user', 'admin'))

            if not result.get('success'):
                flash(result.get('error') or 'Échec comparaison.')
                return redirect(url_for('upload'))

            for pending in pendings:
                if pending.filepath:
                    safe_remove_file(pending.filepath)
                db.delete(pending)

            v = result.get('vlookup') or {}
            ref_count = result.get('reference_count', 0)
            cons_count = result.get('consolidated_count', 0)
            save_treatment_snapshot(db, user=session.get('user', 'admin'), nb_fichiers=len(pendings))
            db.commit()

            if treatment:
                log_step(
                    db, treatment, 'online', 'Comparaison RECHERCHEV',
                    f"{ref_count:,} NIU en ligne · {cons_count:,} dans le consolidé · "
                    f"{v.get('declarants', 0)} déclarants · {v.get('neants', 0)} néants · "
                    f"{v.get('defaillants', 0)} défaillants".replace(',', ' '),
                )
                set_step(db, treatment, 5)

            flash(
                f"RECHERCHEV terminé — {ref_count:,} contribuable(s) · "
                f"consolidé {cons_count:,} · "
                f"{v.get('declarants', 0)} décl. · {v.get('neants', 0)} néant · "
                f"{v.get('defaillants', 0)} défaill.".replace(',', ' ')
            )
        except Exception as e:
            db.rollback()
            flash(f'Erreur Phase 2 : {e}')
        finally:
            db.close()
        return redirect(url_for('upload'))

    @app.route('/process_phase3', methods=['POST'])
    @login_required
    def process_phase3():
        db = SessionLocal()
        treatment = get_treatment(db, session.get('treatment_id'))
        try:
            pendings = db.query(PendingImport).filter(PendingImport.import_phase == 3).all()
            if not pendings:
                flash('Importez la table secteurs (NIU + secteur).')
                return redirect(url_for('upload'))

            filepaths = [p.filepath for p in pendings if p.filepath and os.path.exists(p.filepath)]
            result = run_phase3_sector_lookup(db, filepaths, user=session.get('user', 'admin'))

            if not result.get('success'):
                flash(result.get('error') or 'Échec association secteurs.')
                for err in (result.get('errors') or [])[:3]:
                    flash(err)
                return redirect(url_for('upload'))

            for pending in pendings:
                if pending.filepath:
                    safe_remove_file(pending.filepath)
                db.delete(pending)
            db.commit()

            if treatment:
                log_step(
                    db, treatment, 'sectors', 'Secteurs associés',
                    f"{result.get('updated', 0):,} contribuable(s) mis à jour · "
                    f"{result.get('not_found', 0):,} NIU non trouvé(s)".replace(',', ' '),
                )
                set_step(db, treatment, 6)

            flash(f"Secteurs associés — {result.get('updated', 0)} mise(s) à jour · passez à l'étape Chiffre d'affaires.")
        except Exception as e:
            db.rollback()
            flash(f'Erreur Phase 3 : {e}')
        finally:
            db.close()
        return redirect(url_for('upload'))

    @app.route('/import/skip_sectors', methods=['POST'])
    @login_required
    def import_skip_sectors():
        """Passe à l'étape résultats si les secteurs viennent déjà du fichier en ligne."""
        db = SessionLocal()
        treatment = get_treatment(db, session.get('treatment_id'))
        try:
            with_sector = db.query(Contribuable).filter(
                Contribuable.secteur.isnot(None), Contribuable.secteur != ''
            ).count()
            if with_sector == 0:
                flash('Importez le fichier secteurs (NIU + Secteur CIME) à l\'étape 5.')
                return redirect(url_for('upload'))
            from services.en_ligne_store import mark_sectors_applied
            mark_sectors_applied(db, commit=False)
            if treatment:
                log_step(db, treatment, 'sectors', 'Secteurs conservés', 'Secteurs déjà présents (fichier en ligne).')
                set_step(db, treatment, 6)
            db.commit()
            flash('Étape secteurs ignorée — secteurs déjà renseignés · étape Chiffre d\'affaires.')
        finally:
            db.close()
        return redirect(url_for('upload'))

    @app.route('/process_phase4', methods=['POST'])
    @login_required
    def process_phase4():
        db = SessionLocal()
        treatment = get_treatment(db, session.get('treatment_id'))
        try:
            pendings = db.query(PendingImport).filter(PendingImport.import_phase == 4).all()
            current_paths = []
            previous_paths = []
            for p in pendings:
                path = p.filepath
                if not path or not os.path.exists(path):
                    continue
                if _pending_ca_slot(p) == 'previous':
                    previous_paths.append(path)
                else:
                    current_paths.append(path)

            if not current_paths:
                flash('Importez le fichier CA de l\'année en cours (colonnes CA_TAXABLE, CA_EXPORT, CA_EXONERE).')
                return redirect(url_for('upload'))

            year_current = _parse_year(treatment.period if treatment else None)
            year_previous = year_current - 1 if year_current else None

            result = run_ca_analysis(
                db,
                current_paths=current_paths,
                previous_paths=previous_paths,
                year_current=year_current,
                year_previous=year_previous,
                user=session.get('user', 'admin'),
            )

            if not result.get('success'):
                flash(result.get('error') or 'Échec analyse CA.')
                return redirect(url_for('upload'))

            for pending in pendings:
                if pending.filepath:
                    safe_remove_file(pending.filepath)
                db.delete(pending)
            db.commit()

            if treatment:
                log_step(
                    db, treatment, 'ca', 'CA par sous-secteur',
                    f"{result.get('sous_secteurs', 0)} sous-secteur(s) · "
                    f"{result.get('mapped', 0):,} NIU mappés · "
                    f"{result.get('excluded', 0):,} #N/A exclus · "
                    f"Total CA {result.get('year_current')}: "
                    f"{result.get('total_ca_current', 0):,.0f} FCFA".replace(',', ' '),
                )
                finish_treatment(db, treatment)

            flash(
                f"Analyse CA terminée — {result.get('sous_secteurs', 0)} sous-secteur(s) · "
                f"{result.get('excluded', 0):,} ligne(s) #N/A exclue(s).".replace(',', ' ')
            )
        except Exception as e:
            db.rollback()
            flash(f'Erreur analyse CA : {e}')
        finally:
            db.close()
        return redirect(url_for('upload'))

    @app.route('/import/skip_ca', methods=['POST'])
    @login_required
    def import_skip_ca():
        db = SessionLocal()
        treatment = get_treatment(db, session.get('treatment_id'))
        try:
            for p in db.query(PendingImport).filter(PendingImport.import_phase == 4).all():
                if p.filepath:
                    safe_remove_file(p.filepath)
                db.delete(p)
            if treatment:
                log_step(db, treatment, 'ca', 'CA ignorée', 'Étape chiffre d\'affaires passée.')
                finish_treatment(db, treatment)
            db.commit()
            flash('Étape CA ignorée — résultats disponibles.')
        finally:
            db.close()
        return redirect(url_for('upload'))

    @app.route('/import/goto/<int:step_num>', methods=['POST'])
    @login_required
    def import_goto_step(step_num):
        db = SessionLocal()
        treatment = get_treatment(db, session.get('treatment_id'))
        try:
            if treatment:
                set_step(db, treatment, step_num)
        finally:
            db.close()
        return redirect(url_for('upload'))

    @app.route('/import/restart', methods=['POST'])
    @login_required
    def import_restart():
        db = SessionLocal()
        try:
            clear_consolidated_artifacts(db)
            clear_ca_analysis(db)
            session.pop('import_step', None)
            session.pop('treatment_id', None)
            for p in db.query(PendingImport).all():
                if p.filepath:
                    safe_remove_file(p.filepath)
                db.delete(p)
            db.commit()
        finally:
            db.close()
        flash('Nouveau traitement — paramètres réinitialisés.')
        return redirect(url_for('upload'))

    @app.route('/download_comparaison')
    @login_required
    def download_comparaison():
        """Export fichier en ligne NHR + colonne Statut (RECHERCHEV consolidé)."""
        db = SessionLocal()
        try:
            if db.query(Contribuable).filter(Contribuable.etat.isnot(None)).count() == 0:
                flash('Lancez d\'abord la comparaison RECHERCHEV (étape 4).')
                return redirect(url_for('upload'))
            bio = vlookup_comparison_to_bytes(db)
            if bio is None:
                flash('Fichier en ligne introuvable — relancez la comparaison RECHERCHEV (étape 4).')
                return redirect(url_for('upload'))
            with_sector = sectors_applied(db)
            return send_file(
                bio, download_name=export_download_name(with_sector), as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        finally:
            db.close()

    @app.route('/download_consolide')
    @login_required
    def download_consolide():
        db = SessionLocal()
        try:
            if not consolidated_is_ready(db):
                flash('Aucun fichier consolidé.')
                return redirect(url_for('upload'))
            from services.consolidation import get_consolidated_export_rows
            rows = get_consolidated_export_rows(db)
            if not rows:
                flash('Consolidation vide.')
                return redirect(url_for('upload'))
            bio = BytesIO()
            pd.DataFrame(rows).to_excel(bio, index=False, sheet_name='Consolidé')
            bio.seek(0)
            return send_file(
                bio, download_name='fichier_consolide.xlsx', as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        finally:
            db.close()

    @app.route('/download_consolide_sans_etat')
    @login_required
    def download_consolide_sans_etat():
        db = SessionLocal()
        try:
            consolidated = load_consolidated_dict(db)
            if not consolidated:
                flash('Aucune donnée consolidée.')
                return redirect(url_for('upload'))
            rows = _consolidated_rows_for_export_sans_etat(consolidated)
            bio = BytesIO()
            pd.DataFrame(rows).to_excel(bio, index=False, sheet_name='TCD consolidé')
            bio.seek(0)
            return send_file(
                bio, download_name='tcd_consolide_sans_etat.xlsx', as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        finally:
            db.close()

    @app.route('/download_tcd_secteur')
    @login_required
    def download_tcd_secteur():
        db = SessionLocal()
        try:
            rows = sector_kpi_rows_for_export(db)
            if not rows:
                flash('Aucune statistique secteur — terminez la comparaison.')
                return redirect(url_for('upload'))
            bio = sector_tcd_to_bytes(rows)
            return send_file(
                bio, download_name='tcd_secteur.xlsx', as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        finally:
            db.close()

    @app.route('/download_tcd_sous_secteur')
    @login_required
    def download_tcd_sous_secteur():
        db = SessionLocal()
        try:
            if not sectors_applied(db):
                flash('Associez d\'abord les secteurs (étape 5).')
                return redirect(url_for('upload'))
            rows = sous_secteur_kpi_rows_for_export(db)
            if not rows:
                flash('Aucune statistique sous-secteur.')
                return redirect(url_for('upload'))
            bio = sous_secteur_tcd_to_bytes(rows)
            return send_file(
                bio, download_name='tcd_sous_secteur.xlsx', as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        finally:
            db.close()

    @app.route('/download_reliquataires_sous_secteur')
    @login_required
    def download_reliquataires_sous_secteur():
        db = SessionLocal()
        try:
            if not sectors_applied(db):
                flash('Associez d\'abord les secteurs (étape 5).')
                return redirect(url_for('upload'))
            rows = reliquataires_sous_secteur_rows_for_export(db)
            if not rows:
                flash('Aucune donnée reliquataires par sous-secteur.')
                return redirect(url_for('upload'))
            bio = reliquataires_sous_secteur_to_bytes(rows)
            return send_file(
                bio, download_name='reliquataires_par_sous_secteur.xlsx', as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        finally:
            db.close()

    @app.route('/download_ca_sous_secteur')
    @login_required
    def download_ca_sous_secteur():
        db = SessionLocal()
        try:
            rows, info = ca_table_rows(db)
            if not rows:
                flash('Aucune analyse CA — terminez l\'étape 6 ou importez un fichier CA.')
                return redirect(url_for('upload'))
            bio = ca_sous_secteur_to_bytes(
                rows,
                col_current=info['col_current'],
                col_previous=info['col_previous'],
            )
            return send_file(
                bio, download_name='ca_par_sous_secteur.xlsx', as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        finally:
            db.close()

    @app.route('/download_consolide_ca')
    @login_required
    def download_consolide_ca():
        """Fichier en ligne mis a jour + RECHERCHEV Total CA + sous-secteur (controle avant aggregation)."""
        db = SessionLocal()
        try:
            rows, info = consolide_ca_export_rows(db)
            if not rows:
                flash('Lancez d\'abord le calcul CA (étape 6) pour générer le fichier en ligne mis a jour.')
                return redirect(url_for('upload'))
            bio = BytesIO()
            pd.DataFrame(rows).to_excel(bio, index=False, sheet_name='En ligne + CA')
            bio.seek(0)
            return send_file(
                bio,
                download_name='fichier_en_ligne_mis_a_jour_avec_ca.xlsx',
                as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        finally:
            db.close()

    @app.route('/download_journal')
    @login_required
    def download_journal():
        db = SessionLocal()
        try:
            treatment = get_treatment(db, session.get('treatment_id'))
            if not treatment:
                flash('Aucun journal de traitement.')
                return redirect(url_for('upload'))
            log = load_log(treatment)
            lines = [
                f"Traitement : {treatment.name}",
                f"Période : {treatment.period}",
                f"Utilisateur : {treatment.user}",
                f"Début : {treatment.started_at}",
                f"Fin : {treatment.finished_at or '—'}",
                f"Statut : {treatment.status}",
                '',
                'Journal des étapes :',
            ]
            for entry in log:
                lines.append(f"[{entry.get('at', '')}] {entry.get('title', '')} — {entry.get('detail', '')}")
            bio = BytesIO('\n'.join(lines).encode('utf-8'))
            bio.seek(0)
            return send_file(bio, download_name=f"journal_{treatment.id}.txt", as_attachment=True, mimetype='text/plain')
        finally:
            db.close()

    @app.route('/ca_sous_secteur_detail')
    @login_required
    def ca_sous_secteur_detail():
        sous_secteur = (request.args.get('sous_secteur') or '').strip()
        db = SessionLocal()
        try:
            rows, summary = ca_negative_gap_details(db, sous_secteur)
            if not summary:
                flash('Analyse CA indisponible. Lancez d’abord l’étape 6.')
                return redirect(url_for('upload'))
            return render_template('ca_sous_secteur_detail.html', rows=rows, summary=summary)
        finally:
            db.close()

    # Compatibilité anciennes routes
    def _goto_step(step_num):
        db = SessionLocal()
        treatment = get_treatment(db, session.get('treatment_id'))
        try:
            if treatment:
                set_step(db, treatment, step_num)
        finally:
            db.close()
        return redirect(url_for('upload'))

    @app.route('/import/continue', methods=['POST'])
    @login_required
    def import_continue():
        return _goto_step(4)

    @app.route('/import/back', methods=['POST'])
    @login_required
    def import_back_step1():
        return _goto_step(2)
